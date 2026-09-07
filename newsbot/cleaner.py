"""데이터 정제(clean) 모듈.

raw 저장소의 원본을 읽어 아래 규칙을 적용한 뒤 clean 저장소에 적재한다.

1. **필수 필드 검증** : title / url / content 가 없으면 폐기(사유를 로그로 남김)
2. **텍스트 정규화**  : 유니코드 NFC, HTML 엔티티 해제, 제로폭·중복 공백 제거, 길이 제한
3. **날짜 형식 통일** : RFC822 / ISO8601 / '2026년 8월 18일' → 'YYYY-MM-DD HH:MM:SS' (KST)
4. **결측값 처리**    : 카테고리 → '미분류', 기자 → '미상', 발행일 없음 → 수집일로 대체
5. **중복 처리 정책** : url 해시 기준으로 skip(기본) 또는 upsert

raw 와 clean 을 나누는 이유
- raw 는 수집 시점의 사실을 그대로 보존하는 **원장**이다. 파싱/정제 규칙이 바뀌어도
  다시 수집하지 않고 재처리할 수 있고, 수집 오류의 원인 추적이 가능하다.
- clean 은 분석/요약/리포트가 신뢰할 수 있는 **정형 데이터**다. 스키마와 품질이 보장된다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .logger import get_logger
from .storage import Storage
from .utils import (
    normalize_text,
    now_str,
    to_date_string,
    to_kst_string,
    truncate,
    url_hash,
)

log = get_logger("cleaner")

DUPLICATE_POLICIES = ("skip", "upsert")


@dataclass
class CleanStats:
    """정제 실행 결과 집계."""

    total: int = 0
    inserted: int = 0
    updated: int = 0
    duplicated: int = 0
    invalid: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def add_reason(self, reason: str) -> None:
        self.reasons[reason] = self.reasons.get(reason, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "inserted": self.inserted,
            "updated": self.updated,
            "duplicated": self.duplicated,
            "invalid": self.invalid,
            "reasons": dict(self.reasons),
        }


class Cleaner:
    def __init__(self, config, storage: Storage):
        self.config = config
        self.storage = storage
        self.rules = config.get("cleaning", {}) or {}

    # ------------------------------------------------------------------ 실행
    def run(
        self,
        *,
        limit: int | None = None,
        on_duplicate: str | None = None,
        reprocess: bool = False,
    ) -> CleanStats:
        policy = (on_duplicate or self.rules.get("on_duplicate") or "skip").lower()
        if policy not in DUPLICATE_POLICIES:
            raise ValueError(f"중복 정책은 {DUPLICATE_POLICIES} 중 하나여야 합니다: {policy}")

        rows = self.storage.fetch_raw(only_unprocessed=not reprocess, limit=limit)
        stats = CleanStats(total=len(rows))
        if not rows:
            log.info("정제할 raw 데이터가 없습니다.")
            return stats

        log.info("정제 시작: %d건 (중복 정책=%s%s)", len(rows), policy,
                 ", 전체 재처리" if reprocess else "")

        processed_ids: list[int] = []
        for row in rows:
            processed_ids.append(int(row["id"]))
            try:
                record = self._normalize(row)
            except ValueError as exc:
                stats.invalid += 1
                stats.add_reason(str(exc))
                log.warning("정제 제외 (raw_id=%s): %s", row["id"], exc)
                continue
            except Exception as exc:  # 예상치 못한 오류도 한 건만 실패시킨다
                stats.invalid += 1
                stats.add_reason("예외")
                log.error("정제 중 오류 (raw_id=%s): %s", row["id"], exc)
                continue

            existing = self.storage.find_clean_by_hash(record["url_hash"])
            if existing is None:
                self.storage.insert_clean(record)
                stats.inserted += 1
            elif policy == "upsert":
                self.storage.upsert_clean(record, int(existing["id"]))
                stats.updated += 1
                log.debug("중복 upsert: %s", record["url"])
            else:
                stats.duplicated += 1
                log.debug("중복 skip: %s", record["url"])

        self.storage.mark_raw_processed(processed_ids)

        log.info(
            "정제 완료: 신규 %d건, 갱신 %d건, 중복 %d건, 폐기 %d건",
            stats.inserted, stats.updated, stats.duplicated, stats.invalid,
        )
        if stats.reasons:
            log.info("폐기 사유: %s", ", ".join(f"{k} {v}건" for k, v in stats.reasons.items()))
        return stats

    # ------------------------------------------------------------------ 규칙
    def _normalize(self, row) -> dict[str, Any]:
        """raw 한 건을 clean 레코드로 변환한다. 규칙 위반 시 ValueError."""
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("payload JSON 손상") from exc
        if not isinstance(payload, dict):
            raise ValueError("payload 형식 오류")

        # --- 2) 텍스트 정규화 ------------------------------------------------
        title = normalize_text(payload.get("title"), keep_newlines=False)
        url = (payload.get("link") or row["url"] or "").strip()
        description = normalize_text(payload.get("description"), keep_newlines=False)
        content = normalize_text(payload.get("content"))

        if not content and self.rules.get("content_fallback_to_description", True):
            content = description

        max_len = int(self.rules.get("max_content_length", 20000))
        content = truncate(content, max_len, suffix="")

        # --- 1) 필수 필드 검증 -----------------------------------------------
        values = {"title": title, "url": url, "content": content}
        for field_name in self.rules.get("required_fields", ["title", "url", "content"]):
            if not values.get(field_name):
                raise ValueError(f"필수 필드 누락: {field_name}")

        if len(title) < int(self.rules.get("min_title_length", 5)):
            raise ValueError("제목이 너무 짧음")
        if len(content) < int(self.rules.get("min_content_length", 60)):
            raise ValueError("본문이 너무 짧음")

        # --- 3) 날짜 형식 통일 ------------------------------------------------
        collected_at = to_kst_string(row["collected_at"]) or now_str()
        published_at = to_kst_string(payload.get("pub_date")) or collected_at

        # --- 4) 결측값 처리 ---------------------------------------------------
        category = normalize_text(payload.get("category") or row["category"], keep_newlines=False)
        category = category or self.rules.get("missing_category", "미분류")
        author = normalize_text(payload.get("author"), keep_newlines=False)
        author = author or self.rules.get("missing_author", "미상")

        return {
            "raw_id": int(row["id"]),
            "url_hash": url_hash(url),
            "url": url,
            "title": title,
            "content": content,
            "description": description,
            "category": category,
            "source": row["source"],
            "source_name": row["source_name"],
            "author": author,
            "collect_method": row["collect_method"],
            "published_at": published_at,
            "published_date": to_date_string(published_at),
            "collected_at": collected_at,
            "collected_date": to_date_string(collected_at),
            "content_length": len(content),
        }

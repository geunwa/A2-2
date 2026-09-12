"""AI 기반 뉴스 요약.

흐름: clean 저장소에서 대상 선택 → 프롬프트 구성 → AI API 호출 → 결과 저장
정책
- 이미 요약된 뉴스는 기본 스킵(``--force`` 로 재요약)
- API 실패는 **로깅 후 해당 건만 스킵**하고 전체 작업은 계속한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..logger import get_logger
from ..storage import Storage
from ..utils import truncate
from .client import AIClient, AIError
from .mock import MOCK_LABEL, mock_summarize

log = get_logger("ai.summarize")

SYSTEM_PROMPT = (
    "당신은 한국어 뉴스 요약 전문가입니다. 기사에 실제로 있는 사실만 사용하고, "
    "추측이나 배경 설명을 덧붙이지 마세요. 군더더기 없는 평서문으로 작성합니다."
)

USER_PROMPT = """다음 뉴스 기사를 한국어로 요약해 주세요.

[요구사항]
- {max_chars}자 이내
- 2~3문장
- 핵심 사실(누가/무엇을/어떻게)을 우선 포함
- 머리말("이 기사는", "요약:") 없이 요약문만 출력

[제목]
{title}

[본문]
{content}
"""


@dataclass
class SummarizeStats:
    target: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"target": self.target, "success": self.success,
                "failed": self.failed, "skipped": self.skipped}


class Summarizer:
    def __init__(self, config, storage: Storage, client: AIClient):
        self.config = config
        self.storage = storage
        self.client = client
        self.max_chars = int(config.get("ai.summary.max_chars", 200))
        self.max_input = int(config.get("ai.summary.max_input_chars", 4000))

    # ------------------------------------------------------------------ 대상
    def select_targets(
        self,
        *,
        mode: str = "unsummarized",
        news_id: int | None = None,
        limit: int | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        force: bool = False,
    ) -> list[Any]:
        """요약 대상 뉴스 목록을 고른다. mode: unsummarized | all | id"""
        if news_id is not None:
            row = self.storage.get_news(int(news_id))
            return [row] if row else []

        if mode == "id":
            log.warning("mode='id' 인데 news_id 가 지정되지 않았습니다.")
            return []

        status = None if (mode == "all" or force) else "unsummarized"
        return self.storage.query_news(
            status=status, category=category, date_from=date_from, date_to=date_to,
            limit=limit, order_by="published_at", order="DESC",
        )

    # ------------------------------------------------------------------ 실행
    def run(
        self,
        *,
        mode: str = "unsummarized",
        news_id: int | None = None,
        limit: int | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        force: bool = False,
        max_chars: int | None = None,
        dry_run: bool = False,
    ) -> SummarizeStats:
        max_chars = int(max_chars or self.max_chars)
        rows = self.select_targets(
            mode=mode, news_id=news_id, limit=limit, category=category,
            date_from=date_from, date_to=date_to, force=force,
        )
        total = len(rows)                                                    # ← 캐싱
        stats = SummarizeStats(target=total)
        if not rows:
            log.info("요약 대상이 없습니다.")
            return stats

        log.info("요약 대상: %d건 (모델=%s, 최대 %d자)", total, self.client.label, max_chars)
        skip_done = bool(self.config.get("ai.summary.skip_if_summarized", True))

        for index, row in enumerate(rows, start=1):
            news_id_value = int(row["id"])
            already = bool((row["summary"] or "").strip())
            if already and skip_done and not force:
                stats.skipped += 1
                log.info("[%d/%d] ID=%d 이미 요약됨 - 스킵", index, total, news_id_value)
                continue

            content = row["content"] or ""
            if not content.strip():
                stats.failed += 1
                log.warning("[%d/%d] ID=%d 본문이 비어 있어 스킵", index, total, news_id_value)
                continue

            if dry_run:
                stats.skipped += 1
                log.info("[%d/%d] ID=%d (dry-run) 호출 생략", index, total, news_id_value)
                continue

            try:
                summary = self.summarize_one(row["title"] or "", content, max_chars)
            except AIError as exc:
                stats.failed += 1
                log.error("[%d/%d] ID=%d 요약 실패: %s", index, total, news_id_value, exc)
                continue

            if not summary:
                stats.failed += 1
                log.error("[%d/%d] ID=%d 요약 결과가 비었습니다", index, total, news_id_value)
                continue

            model = MOCK_LABEL if self.client.is_mock else self.client.label
            self.storage.save_summary(news_id_value, summary, model)
            stats.success += 1
            log.info(
                "[%d/%d] ID=%d 요약 완료 (%d자 → %d자)",
                index, total, news_id_value, len(content), len(summary),
            )

        log.info("요약 완료: %d건 성공, %d건 실패, %d건 스킵",
                 stats.success, stats.failed, stats.skipped)
        return stats

    # ------------------------------------------------------------------ 단건
    def summarize_one(self, title: str, content: str, max_chars: int | None = None) -> str:
        max_chars = int(max_chars or self.max_chars)
        body = truncate(content, self.max_input, suffix="")

        if self.client.is_mock:
            return mock_summarize(title, body, max_chars)

        prompt = USER_PROMPT.format(max_chars=max_chars, title=title, content=body)
        text = self.client.complete(
            prompt, system=SYSTEM_PROMPT,
            max_tokens=max(256, max_chars * 3), temperature=0.2,
        )
        return truncate(_clean_summary(text), max_chars * 2, suffix="")


def _clean_summary(text: str) -> str:
    """모델이 붙이는 머리말/따옴표를 제거한다."""
    cleaned = text.strip().strip('"').strip("'").strip()
    for prefix in ("요약:", "요약문:", "다음은", "이 기사는"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].lstrip(" :-")
    return cleaned.strip()
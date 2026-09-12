"""AI 기반 인사이트 분석.

조건(기간 / 카테고리)에 맞는 뉴스를 한 번에 모아 종합 분석을 요청하고,
결과를 ``analyses`` 테이블에 저장해 리포트에서 재사용한다.

분석 항목 (4종)
    1. 주요 트렌드     2. 핵심 키워드
    3. 공통점/차이점   4. 시사점
"""

from __future__ import annotations

from typing import Any

from ..logger import get_logger
from ..storage import Storage
from ..utils import truncate
from .client import AIClient, AIError, extract_json
from .mock import MOCK_LABEL, mock_analyze

log = get_logger("ai.analyze")

SYSTEM_PROMPT = (
    "당신은 한국어 뉴스 데이터를 분석하는 미디어 애널리스트입니다. "
    "제공된 기사 목록에 근거해서만 분석하고, 근거가 없는 단정은 피하세요. "
    "반드시 지정된 JSON 스키마만 출력합니다."
)

USER_PROMPT = """아래는 {period} 기간의 {category} 뉴스 {count}건입니다.
전체를 종합해 분석해 주세요.

[출력 형식] - 아래 JSON 객체 하나만 출력 (설명/코드펜스 없이)
{{
  "overview": "3문장 이내 총평",
  "trends": ["주요 트렌드 3~5개"],
  "keywords": ["핵심 키워드 5~8개(단어만)"],
  "comparison": ["기사들의 공통점과 차이점 2~4개"],
  "implications": ["시사점 2~4개"]
}}

[기사 목록]
{articles}
"""


class Analyzer:
    def __init__(self, config, storage: Storage, client: AIClient):
        self.config = config
        self.storage = storage
        self.client = client
        self.max_articles = int(config.get("ai.analyze.max_articles", 60))
        self.snippet_chars = int(config.get("ai.analyze.snippet_chars", 350))

    # ------------------------------------------------------------------ 대상
    def collect_articles(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        category: str | None = None,
        keyword: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.storage.query_news(
            date_from=date_from, date_to=date_to, category=category, keyword=keyword,
            limit=limit or self.max_articles, order_by="published_at", order="DESC",
        )
        articles = []
        for row in rows:
            snippet = (row["summary"] or "").strip() or (row["content"] or "")
            articles.append({
                "id": int(row["id"]),
                "title": row["title"],
                "category": row["category"],
                "date": row["published_date"],
                "snippet": truncate(snippet, self.snippet_chars, suffix=""),
            })
        return articles

    # ------------------------------------------------------------------ 실행
    def run(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        category: str | None = None,
        keyword: str | None = None,
        limit: int | None = None,
        save: bool = True,
    ) -> dict[str, Any] | None:
        articles = self.collect_articles(
            date_from=date_from, date_to=date_to, category=category, keyword=keyword, limit=limit
        )
        if not articles:
            log.warning("분석 대상 뉴스가 없습니다. (조건을 확인하세요)")
            return None

        log.info("분석 대상: %d건", len(articles))
        log.info("AI 분석 요청 중... (%s)", self.client.label)

        if self.client.is_mock:
            parsed = mock_analyze(articles)
            raw_text = None
            model = MOCK_LABEL
        else:
            prompt = USER_PROMPT.format(
                period=_period_label(date_from, date_to),
                category=category or "전체",
                count=len(articles),
                articles=_format_articles(articles),
            )
            try:
                raw_text = self.client.complete(
                    prompt, system=SYSTEM_PROMPT, max_tokens=2048, temperature=0.3
                )
                parsed = extract_json(raw_text)
            except AIError as exc:
                log.error("AI 분석 실패: %s", exc)
                return None
            model = self.client.label

        # result 구성 전에 유효성 검사 — 불필요한 dict 생성 방지
        if not any([
            _as_list(parsed.get("trends")),
            _as_list(parsed.get("keywords")),
            _as_list(parsed.get("implications")),
        ]):
            log.error("AI 분석 결과에서 유효한 항목을 찾지 못했습니다.")
            return None

        result = {
            "date_from": date_from,
            "date_to": date_to,
            "category": category,
            "target_count": len(articles),
            "provider": self.client.provider,
            "model": model,
            "overview": str(parsed.get("overview") or "").strip(),
            "trends": _as_list(parsed.get("trends")),
            "keywords": _as_list(parsed.get("keywords")),
            "comparison": _as_list(parsed.get("comparison")),
            "implications": _as_list(parsed.get("implications")),
            "raw_response": raw_text,
        }

        if save:
            result["id"] = self.storage.insert_analysis(result)
            log.info("분석 완료 (analysis_id=%s)", result["id"])
        else:
            log.info("분석 완료 (저장 생략)")
        return result

# ---------------------------------------------------------------------- 유틸
def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip(" -•") for p in value.split("\n") if p.strip()]
        return parts or [value.strip()]
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append(" / ".join(f"{k}: {v}" for k, v in item.items()))
            elif item is not None and str(item).strip():
                out.append(str(item).strip())
        return out
    return [str(value)]


def _period_label(date_from: str | None, date_to: str | None) -> str:
    if date_from and date_to:
        return f"{date_from} ~ {date_to}"
    if date_from:
        return f"{date_from} 이후"
    if date_to:
        return f"{date_to} 이전"
    return "전체"


def _format_articles(articles: list[dict[str, Any]]) -> str:
    lines = []
    for item in articles:
        lines.append(
            f"- [{item['date'] or '날짜미상'}][{item['category'] or '미분류'}] "
            f"{item['title']}\n  {item['snippet']}"
        )
    return "\n".join(lines)


def format_analysis(result: dict[str, Any]) -> str:
    """콘솔/리포트에 쓰는 사람이 읽기 좋은 형태로 변환."""
    lines: list[str] = ["=== AI 인사이트 분석 결과 ==="]
    meta = []
    if result.get("date_from") or result.get("date_to"):
        meta.append(f"기간: {_period_label(result.get('date_from'), result.get('date_to'))}")
    meta.append(f"카테고리: {result.get('category') or '전체'}")
    meta.append(f"대상: {result.get('target_count', 0)}건")
    meta.append(f"모델: {result.get('model', '-')}")
    lines.append(" | ".join(meta))

    if result.get("overview"):
        lines.append("")
        lines.append("[총평]")
        lines.append(result["overview"])

    sections = [
        ("주요 트렌드", result.get("trends")),
        ("공통점/차이점", result.get("comparison")),
        ("시사점", result.get("implications")),
    ]
    if result.get("keywords"):
        lines.append("")
        lines.append("[핵심 키워드]")
        lines.append(", ".join(result["keywords"]))

    for title, items in sections:
        if not items:
            continue
        lines.append("")
        lines.append(f"[{title}]")
        lines.extend(f"- {item}" for item in items)

    return "\n".join(lines)

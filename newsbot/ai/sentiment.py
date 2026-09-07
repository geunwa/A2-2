"""감성 분석 (보너스 과제).

각 뉴스의 논조를 긍정/부정/중립으로 분류하고 점수(-1.0 ~ 1.0)와 근거를 저장한다.
결과는 ``report --charts`` 의 감성 분포 파이차트로 시각화된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..logger import get_logger
from ..storage import Storage
from ..utils import truncate
from .client import AIClient, AIError, extract_json
from .mock import MOCK_LABEL, mock_sentiment

log = get_logger("ai.sentiment")

VALID_LABELS = ("긍정", "부정", "중립")

SYSTEM_PROMPT = "당신은 한국어 뉴스의 논조를 분류하는 분석가입니다. 지정된 JSON 만 출력합니다."

USER_PROMPT = """다음 뉴스의 전반적인 논조를 판정해 주세요.

[출력 형식] - JSON 객체 하나만 출력
{{"sentiment": "긍정|부정|중립", "score": -1.0~1.0 사이 실수, "reason": "판정 근거 한 문장"}}

[제목]
{title}

[본문]
{content}
"""


@dataclass
class SentimentStats:
    target: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"target": self.target, "success": self.success,
                "failed": self.failed, "skipped": self.skipped}


class SentimentAnalyzer:
    def __init__(self, config, storage: Storage, client: AIClient):
        self.config = config
        self.storage = storage
        self.client = client
        self.max_input = int(config.get("ai.sentiment.max_input_chars", 1200))

    def run(
        self,
        *,
        news_id: int | None = None,
        limit: int | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        force: bool = False,
    ) -> SentimentStats:
        if news_id is not None:
            row = self.storage.get_news(int(news_id))
            rows = [row] if row else []
        else:
            rows = self.storage.query_news(
                status=None if force else "unanalyzed",
                category=category, date_from=date_from, date_to=date_to,
                limit=limit, order_by="published_at", order="DESC",
            )

        stats = SentimentStats(target=len(rows))
        if not rows:
            log.info("감성 분석 대상이 없습니다.")
            return stats

        log.info("감성 분석 대상: %d건 (%s)", len(rows), self.client.label)
        for index, row in enumerate(rows, start=1):
            nid = int(row["id"])
            if (row["sentiment"] or "").strip() and not force:
                stats.skipped += 1
                log.info("[%d/%d] ID=%d 이미 분석됨 - 스킵", index, len(rows), nid)
                continue
            try:
                result = self.analyze_one(row["title"] or "", row["content"] or "")
            except AIError as exc:
                stats.failed += 1
                log.error("[%d/%d] ID=%d 감성 분석 실패: %s", index, len(rows), nid, exc)
                continue

            model = MOCK_LABEL if self.client.is_mock else self.client.label
            self.storage.save_sentiment(
                nid, result["sentiment"], result.get("score"), result.get("reason"), model
            )
            stats.success += 1
            log.info("[%d/%d] ID=%d → %s (%.2f)",
                     index, len(rows), nid, result["sentiment"], result.get("score") or 0.0)

        log.info("감성 분석 완료: %d건 성공, %d건 실패, %d건 스킵",
                 stats.success, stats.failed, stats.skipped)
        return stats

    def analyze_one(self, title: str, content: str) -> dict[str, Any]:
        body = truncate(content, self.max_input, suffix="")
        if self.client.is_mock:
            return mock_sentiment(title, body)

        text = self.client.complete(
            USER_PROMPT.format(title=title, content=body),
            system=SYSTEM_PROMPT, max_tokens=300, temperature=0.0,
        )
        parsed = extract_json(text)
        label = str(parsed.get("sentiment", "")).strip()
        if label not in VALID_LABELS:
            label = "중립"
        try:
            score = float(parsed.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        return {
            "sentiment": label,
            "score": max(-1.0, min(1.0, score)),
            "reason": str(parsed.get("reason") or "").strip(),
        }

"""수집기 공통 베이스."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CollectResult:
    """단일 수집 실행 결과."""

    method: str
    source: str
    records: list[dict[str, Any]] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    body_failed: int = 0  # 본문 수집/파싱 실패 전용
    errors: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """수집 실패 — failed 카운터 증가."""
        self.failed += 1
        self.errors.append(message)

    def add_body_error(self, message: str) -> None:
        """본문 실패 — body_failed 카운터 증가 (succeeded는 유지)."""
        self.body_failed += 1
        self.errors.append(message)

    def merge(self, other: "CollectResult") -> "CollectResult":
        """다른 결과를 병합 — 출처가 다르면 에러 메시지에 prefix 추가."""
        self.records.extend(other.records)
        self.succeeded += other.succeeded
        self.failed += other.failed
        self.body_failed += other.body_failed
        if other.source != self.source:
            self.errors.extend(
                f"[{other.source}] {e}" for e in other.errors
            )
        else:
            self.errors.extend(other.errors)
        return self
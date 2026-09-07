"""수집기 공통 자료구조."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CollectResult:
    """한 번의 수집 실행 결과."""

    method: str
    source: str
    records: list[dict[str, Any]] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.failed += 1
        self.errors.append(message)

    def merge(self, other: "CollectResult") -> "CollectResult":
        self.records.extend(other.records)
        self.succeeded += other.succeeded
        self.failed += other.failed
        self.errors.extend(other.errors)
        return self

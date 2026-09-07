"""데이터 내보내기 모듈 (CSV / JSONL / Excel).

- CSV   : utf-8-sig 로 저장해 엑셀에서 한글이 깨지지 않게 한다.
- JSONL : 한 줄에 한 기사(JSON). 재수집/재적재에 유리하다.
- Excel : openpyxl 엔진. 셀 길이 제한(32,767자)을 고려해 본문을 잘라 넣는다.

필터: 기간 / 카테고리 / 상태(--status summarized) / 키워드
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .logger import get_logger
from .storage import Storage, rows_to_dicts
from .utils import now_kst, truncate

log = get_logger("export")

FORMATS = ("csv", "jsonl", "excel")

COLUMNS = [
    "id", "title", "category", "source_name", "author", "collect_method",
    "published_at", "collected_at", "url", "content_length", "summary",
    "summary_length", "summary_model", "sentiment", "sentiment_score",
    "status", "content",
]

EXCEL_CELL_LIMIT = 30000


class Exporter:
    def __init__(self, config, storage: Storage):
        self.config = config
        self.storage = storage

    # ------------------------------------------------------------------ 조회
    def fetch(self, **filters) -> list[dict[str, Any]]:
        rows = self.storage.query_news(order_by="published_at", order="DESC", **filters)
        records = rows_to_dicts(rows)
        return [{col: record.get(col) for col in COLUMNS} for record in records]

    # ------------------------------------------------------------------ 실행
    def export(
        self,
        fmt: str = "csv",
        *,
        output: str | Path | None = None,
        **filters,
    ) -> list[Path]:
        fmt = (fmt or "csv").lower()
        targets = list(FORMATS) if fmt == "all" else [fmt]
        for target in targets:
            if target not in FORMATS:
                raise ValueError(f"지원하지 않는 포맷입니다: {target} (가능: {', '.join(FORMATS)}, all)")

        records = self.fetch(**filters)
        if not records:
            log.warning("내보낼 데이터가 없습니다. (필터 조건을 확인하세요)")
            return []

        log.info("내보내기 대상: %d건", len(records))
        written: list[Path] = []
        for target in targets:
            path = self._resolve_path(target, output if len(targets) == 1 else None)
            writer = {"csv": self._write_csv, "jsonl": self._write_jsonl, "excel": self._write_excel}[target]
            try:
                writer(records, path)
            except Exception as exc:
                log.error("%s 내보내기 실패: %s", target, exc)
                continue
            log.info("%s 저장 완료: %s (%d건)", target.upper(), path, len(records))
            written.append(path)
        return written

    # ------------------------------------------------------------------ 경로
    def _resolve_path(self, fmt: str, output: str | Path | None) -> Path:
        if output:
            path = Path(output)
            if not path.is_absolute():
                path = self.config.base_dir / path
            return path
        export_dir = self.config.path("paths.export_dir", mkdir=True, is_dir=True)
        ext = {"csv": "csv", "jsonl": "jsonl", "excel": "xlsx"}[fmt]
        return export_dir / f"news_{now_kst().strftime('%Y%m%d_%H%M%S')}.{ext}"

    # ------------------------------------------------------------------ 쓰기
    @staticmethod
    def _write_csv(records: list[dict[str, Any]], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)

    @staticmethod
    def _write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fp:
            for record in records:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _write_excel(records: list[dict[str, Any]], path: Path) -> None:
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Excel 내보내기에는 pandas 와 openpyxl 이 필요합니다.") from exc

        path.parent.mkdir(parents=True, exist_ok=True)
        trimmed = [
            {**r, "content": truncate(r.get("content") or "", EXCEL_CELL_LIMIT, suffix="")}
            for r in records
        ]
        frame = pd.DataFrame(trimmed, columns=COLUMNS)
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            frame.to_excel(writer, index=False, sheet_name="news")
            sheet = writer.sheets["news"]
            widths = {"A": 6, "B": 50, "C": 10, "D": 12, "E": 10, "F": 10,
                      "G": 20, "H": 20, "I": 45, "J": 10, "K": 60}
            for column, width in widths.items():
                sheet.column_dimensions[column].width = width

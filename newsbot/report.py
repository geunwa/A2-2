"""리포트 생성 모듈.

포함 내용
- 수집 현황 요약 (raw / clean / 수집 방법별)
- **품질 지표 5종** : 정제 통과율, 요약 완료율, 카테고리 결측률, 발행일 결측률, 평균 요약 압축률
- **TOP N 집계 3종** : 카테고리 TOP N, 키워드 TOP N, 장문 기사 TOP N
- **AI 인사이트 분석 결과** (analyses 테이블의 최신 결과)
- 생성된 차트 파일 경로

출력: 콘솔 + 파일(TXT / MD)
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any

from .ai.analyzer import format_analysis
from .logger import get_logger
from .storage import Storage
from .utils import now_kst, now_str, tokenize, truncate

log = get_logger("report")


class ReportBuilder:
    def __init__(self, config, storage: Storage):
        self.config = config
        self.storage = storage
        self.top_n = int(config.get("report.top_n", 5))

    # ------------------------------------------------------------------ 수집
    def build(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        category: str | None = None,
        top_n: int | None = None,
        charts: dict[str, Path] | None = None,
        analysis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        top_n = int(top_n or self.top_n)
        filters = {"date_from": date_from, "date_to": date_to, "category": category}

        metrics = self.storage.aggregate_metrics(**filters)
        total = int(metrics.get("total") or 0)
        raw_total = self.storage.count_raw()

        rows = self.storage.query_news(limit=None, **filters)
        keyword_counter: Counter[str] = Counter()
        for row in rows:
            keyword_counter.update(set(tokenize(row["title"] or "")))

        quality = _quality_metrics(metrics, raw_total)
        data: dict[str, Any] = {
            "generated_at": now_str(),
            "filters": {
                "date_from": date_from or "-",
                "date_to": date_to or "-",
                "category": category or "전체",
            },
            "counts": {
                "raw": raw_total,
                "clean": total,
                "by_method": self.storage.method_counts(),
                "period": (metrics.get("first_date") or "-", metrics.get("last_date") or "-"),
            },
            "quality": quality,
            "top": {
                "categories": self.storage.category_counts(**filters)[:top_n],
                "keywords": keyword_counter.most_common(top_n),
                "longest": [
                    (int(r["id"]), r["title"], int(r["content_length"] or 0), r["category"])
                    for r in self.storage.top_articles(top_n, **filters)
                ],
            },
            "daily": self.storage.daily_counts(**filters),
            "sentiment": self.storage.sentiment_counts(**filters),
            "analysis": analysis,
            "charts": {k: str(v) for k, v in (charts or {}).items()},
            "top_n": top_n,
        }
        return data

    # ------------------------------------------------------------------ 렌더
    @staticmethod
    def render(data: dict[str, Any], fmt: str = "md", link_base: Path | None = None) -> str:
        """link_base 를 주면 마크다운의 차트 이미지 링크를 그 폴더 기준 상대 경로로 만든다."""
        return _render_markdown(data, link_base) if fmt == "md" else _render_text(data)

    def save(self, data: dict[str, Any], fmt: str = "md", output: str | Path | None = None) -> Path:
        fmt = "md" if str(fmt).lower() in ("md", "markdown") else "txt"
        if output:
            path = Path(output)
            if not path.is_absolute():
                path = self.config.base_dir / path
        else:
            report_dir = self.config.path("paths.report_dir", mkdir=True, is_dir=True)
            path = report_dir / f"report_{now_kst().strftime('%Y%m%d_%H%M%S')}.{fmt}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(data, fmt, link_base=path.parent), encoding="utf-8")
        log.info("리포트 저장: %s", path)
        return path


# ---------------------------------------------------------------------- 지표
def _pct(numerator: float, denominator: float) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def _quality_metrics(metrics: dict[str, Any], raw_total: int) -> list[dict[str, Any]]:
    total = int(metrics.get("total") or 0)
    summarized = int(metrics.get("summarized") or 0)
    uncategorized = int(metrics.get("uncategorized") or 0)
    no_pubdate = int(metrics.get("no_pubdate") or 0)
    avg_len = float(metrics.get("avg_len") or 0)
    avg_summary = float(metrics.get("avg_summary_len") or 0)

    return [
        {
            "name": "정제 통과율",
            "value": f"{_pct(total, raw_total)}%",
            "detail": f"clean {total}건 / raw {raw_total}건",
        },
        {
            "name": "요약 완료율",
            "value": f"{_pct(summarized, total)}%",
            "detail": f"요약 {summarized}건 / 대상 {total}건",
        },
        {
            "name": "카테고리 결측률",
            "value": f"{_pct(uncategorized, total)}%",
            "detail": f"미분류 {uncategorized}건",
        },
        {
            "name": "발행일 결측률",
            "value": f"{_pct(no_pubdate, total)}%",
            "detail": f"발행일 없음 {no_pubdate}건",
        },
        {
            "name": "평균 요약 압축률",
            "value": f"{_pct(avg_summary, avg_len)}%" if avg_len else "-",
            "detail": f"본문 평균 {avg_len:.0f}자 → 요약 평균 {avg_summary:.0f}자",
        },
    ]


# ---------------------------------------------------------------------- 렌더러
def _relative_link(path_str: str, link_base: Path | None) -> str:
    """마크다운 이미지 링크용 경로. 같은 드라이브면 상대 경로, 아니면 절대 경로."""
    path = Path(path_str)
    if link_base is not None:
        try:
            return Path(os.path.relpath(path, link_base)).as_posix()
        except ValueError:  # 드라이브가 다르면 상대 경로를 만들 수 없다
            pass
    return path.as_posix()


def _render_markdown(data: dict[str, Any], link_base: Path | None = None) -> str:
    f = data["filters"]
    c = data["counts"]
    lines: list[str] = [
        "# 뉴스 분석 리포트",
        "",
        f"- 생성 시각: **{data['generated_at']}**",
        f"- 조건: 기간 `{f['date_from']} ~ {f['date_to']}` / 카테고리 `{f['category']}`",
        f"- 데이터 기간: `{c['period'][0]} ~ {c['period'][1]}`",
        "",
        "## 1. 수집 현황",
        "",
        "| 구분 | 건수 |",
        "|---|---:|",
        f"| raw 저장소 | {c['raw']:,} |",
        f"| clean 저장소 | {c['clean']:,} |",
    ]
    for method, count in c["by_method"]:
        lines.append(f"| 수집 방법 · {method} | {count:,} |")

    lines += ["", "## 2. 품질 지표", "", "| 지표 | 값 | 상세 |", "|---|---:|---|"]
    for item in data["quality"]:
        lines.append(f"| {item['name']} | {item['value']} | {item['detail']} |")

    n = data["top_n"]
    lines += ["", f"## 3. TOP {n} 집계", "", f"### 3-1. 카테고리 TOP {n}", "",
              "| 순위 | 카테고리 | 건수 |", "|---:|---|---:|"]
    for rank, (name, count) in enumerate(data["top"]["categories"], start=1):
        lines.append(f"| {rank} | {name} | {count:,} |")

    lines += ["", f"### 3-2. 제목 키워드 TOP {n}", "", "| 순위 | 키워드 | 등장 기사 수 |", "|---:|---|---:|"]
    for rank, (word, count) in enumerate(data["top"]["keywords"], start=1):
        lines.append(f"| {rank} | {word} | {count:,} |")

    lines += ["", f"### 3-3. 본문이 긴 기사 TOP {n}", "", "| 순위 | ID | 제목 | 카테고리 | 본문 길이 |",
              "|---:|---:|---|---|---:|"]
    for rank, (news_id, title, length, category) in enumerate(data["top"]["longest"], start=1):
        lines.append(f"| {rank} | {news_id} | {truncate(title, 40)} | {category} | {length:,} |")

    if data.get("sentiment"):
        lines += ["", "## 4. 감성 분포", "", "| 감성 | 건수 |", "|---|---:|"]
        lines += [f"| {label} | {count:,} |" for label, count in data["sentiment"]]

    lines += ["", "## 5. AI 인사이트 분석", ""]
    if data.get("analysis"):
        lines.append("```")
        lines.append(format_analysis(data["analysis"]))
        lines.append("```")
    else:
        lines.append("_저장된 분석 결과가 없습니다. `python main.py analyze` 를 먼저 실행하세요._")

    if data.get("charts"):
        lines += ["", "## 6. 차트", ""]
        for name, path in data["charts"].items():
            lines.append(f"- **{name}**: `{path}`")
            lines.append("")
            lines.append(f"  ![{name}]({_relative_link(path, link_base)})")
            lines.append("")

    lines.append("")
    return "\n".join(lines)


def _render_text(data: dict[str, Any]) -> str:
    f = data["filters"]
    c = data["counts"]
    bar = "=" * 60
    lines = [
        bar, " 뉴스 분석 리포트", bar,
        f" 생성 시각 : {data['generated_at']}",
        f" 조건      : {f['date_from']} ~ {f['date_to']} / {f['category']}",
        f" 데이터기간: {c['period'][0]} ~ {c['period'][1]}",
        "",
        "[1] 수집 현황",
        f"  - raw   : {c['raw']:,}건",
        f"  - clean : {c['clean']:,}건",
    ]
    for method, count in c["by_method"]:
        lines.append(f"  - 수집 방법 {method}: {count:,}건")

    lines += ["", "[2] 품질 지표"]
    for item in data["quality"]:
        lines.append(f"  - {item['name']}: {item['value']}  ({item['detail']})")

    n = data["top_n"]
    lines += ["", f"[3] TOP {n} 집계", f"  * 카테고리 TOP {n}"]
    for rank, (name, count) in enumerate(data["top"]["categories"], start=1):
        lines.append(f"    {rank}. {name} - {count:,}건")
    lines.append(f"  * 제목 키워드 TOP {n}")
    for rank, (word, count) in enumerate(data["top"]["keywords"], start=1):
        lines.append(f"    {rank}. {word} - {count:,}건")
    lines.append(f"  * 본문이 긴 기사 TOP {n}")
    for rank, (news_id, title, length, category) in enumerate(data["top"]["longest"], start=1):
        lines.append(f"    {rank}. [ID {news_id}][{category}] {truncate(title, 40)} ({length:,}자)")

    if data.get("sentiment"):
        lines += ["", "[4] 감성 분포"]
        lines += [f"  - {label}: {count:,}건" for label, count in data["sentiment"]]

    lines += ["", "[5] AI 인사이트 분석"]
    if data.get("analysis"):
        lines.append(format_analysis(data["analysis"]))
    else:
        lines.append("  저장된 분석 결과가 없습니다. 'python main.py analyze' 를 먼저 실행하세요.")

    if data.get("charts"):
        lines += ["", "[6] 차트"]
        lines += [f"  - {name}: {path}" for name, path in data["charts"].items()]

    lines += ["", bar]
    return "\n".join(lines)

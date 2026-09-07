"""matplotlib 시각화 모듈.

생성 차트
1. 카테고리별 뉴스 수 (가로 막대) - 크기 비교
2. 일자별 수집 추이 (선 그래프)   - 시간 변화
3. 감성 분포 (도넛, 보너스)       - 구성비

디자인 원칙
- 한글 폰트를 적용하고 마이너스 기호 깨짐(axes.unicode_minus)을 끈다.
- 단일 계열에는 단일 색을 쓰고, 격자/축은 배경으로 물러나게 한다.
- 값은 막대 끝/주요 지점에만 직접 표기해 색에만 의존하지 않는다.
- 감성은 발산형(긍정 파랑 ↔ 중립 회색 ↔ 부정 주황)으로, 색각 이상에서도 구분된다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")  # GUI 없는 환경(CLI)에서 PNG 로만 저장

import matplotlib.pyplot as plt
from matplotlib import font_manager

from .logger import get_logger

log = get_logger("visualize")

# 색: 단일 계열용 기본색 + 감성 발산형 팔레트
PRIMARY = "#3B6FD4"
PRIMARY_SOFT = "#9DB8EA"
INK = "#1F2937"
MUTED = "#6B7280"
GRID = "#E5E7EB"
SENTIMENT_COLORS = {"긍정": "#3B6FD4", "중립": "#9CA3AF", "부정": "#D97706"}

_font_applied: str | None = None


# ---------------------------------------------------------------------- 폰트
def setup_korean_font(config) -> str | None:
    """설정의 후보 목록에서 시스템에 설치된 한글 폰트를 찾아 적용한다."""
    global _font_applied
    if _font_applied:
        return _font_applied

    candidates = config.get("chart.font_candidates", []) or []
    installed = {f.name for f in font_manager.fontManager.ttflist}

    chosen = next((name for name in candidates if name in installed), None)
    if chosen is None:
        chosen = next((name for name in installed
                       if any(k in name for k in ("Gothic", "Nanum", "Malgun", "Noto Sans KR"))), None)

    if chosen:
        plt.rcParams["font.family"] = chosen
        log.info("차트 한글 폰트 적용: %s", chosen)
    else:
        log.warning("한글 폰트를 찾지 못했습니다. 차트의 한글이 깨질 수 있습니다. "
                    "(예: 나눔고딕 설치 후 config.json 의 chart.font_candidates 에 추가)")

    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = int(config.get("chart.dpi", 130))
    plt.rcParams["savefig.bbox"] = "tight"
    _font_applied = chosen or ""
    return chosen


def _new_axes(config, *, figsize: tuple[float, float] | None = None):
    size = figsize or tuple(config.get("chart.figsize", [10, 6]))
    fig, ax = plt.subplots(figsize=size)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=10, length=0)
    return fig, ax


def _save(fig, out_path: Path, dpi: int) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi, facecolor=fig.get_facecolor())
    plt.close(fig)
    log.info("차트 저장: %s", out_path)
    return out_path


# ---------------------------------------------------------------------- 차트
def chart_category_counts(
    config, counts: Sequence[tuple[str, int]], out_path: Path, *, title: str | None = None
) -> Path | None:
    """카테고리별 뉴스 수 (가로 막대)."""
    if not counts:
        log.warning("카테고리 데이터가 없어 차트를 건너뜁니다.")
        return None
    setup_korean_font(config)

    labels = [c[0] for c in counts][::-1]
    values = [c[1] for c in counts][::-1]

    height = max(4.0, 0.45 * len(labels) + 2.0)
    fig, ax = _new_axes(config, figsize=(9.5, height))
    bars = ax.barh(labels, values, color=PRIMARY, height=0.62)

    ax.set_title(title or "카테고리별 뉴스 수", fontsize=14, color=INK, pad=14, loc="left")
    ax.set_xlabel("기사 수", fontsize=10, color=MUTED)
    ax.xaxis.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(values) * 1.15)

    for bar, value in zip(bars, values):
        ax.text(bar.get_width() + max(values) * 0.015, bar.get_y() + bar.get_height() / 2,
                f"{value:,}", va="center", ha="left", fontsize=10, color=INK)

    return _save(fig, out_path, int(config.get("chart.dpi", 130)))


def chart_daily_trend(
    config, counts: Sequence[tuple[str, int]], out_path: Path, *, title: str | None = None
) -> Path | None:
    """일자별 수집 추이 (선 그래프)."""
    if not counts:
        log.warning("일자별 데이터가 없어 차트를 건너뜁니다.")
        return None
    setup_korean_font(config)

    labels = [c[0] for c in counts]
    values = [c[1] for c in counts]

    fig, ax = _new_axes(config)
    if len(labels) == 1:
        # 데이터가 하루뿐이면 선 대신 막대로 그린다(점 하나짜리 꺾은선은 읽히지 않는다).
        ax.bar(labels, values, color=PRIMARY, width=0.3)
        ax.set_xlim(-1, 1)
    else:
        ax.plot(labels, values, color=PRIMARY, linewidth=2, marker="o",
                markersize=8, markerfacecolor="white", markeredgewidth=2, markeredgecolor=PRIMARY)
        ax.fill_between(range(len(labels)), values, color=PRIMARY_SOFT, alpha=0.25)

    ax.set_title(title or "일자별 뉴스 수집 추이", fontsize=14, color=INK, pad=14, loc="left")
    ax.set_ylabel("수집 건수", fontsize=10, color=MUTED)
    ax.yaxis.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(values) * 1.25 or 1)

    if len(labels) > 8:  # 라벨 충돌 방지
        step = max(1, len(labels) // 8)
        ax.set_xticks(range(0, len(labels), step))
        ax.set_xticklabels(labels[::step], rotation=30, ha="right")
    else:
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=0 if len(labels) <= 5 else 30,
                           ha="center" if len(labels) <= 5 else "right")

    peak = max(range(len(values)), key=lambda i: values[i])
    marks = {peak, len(values) - 1}
    for i in marks:  # 최고점과 마지막 지점만 직접 표기
        ax.annotate(f"{values[i]:,}", (i, values[i]), textcoords="offset points",
                    xytext=(0, 12), ha="center", fontsize=10, color=INK)

    return _save(fig, out_path, int(config.get("chart.dpi", 130)))


def chart_sentiment(
    config, counts: Sequence[tuple[str, int]], out_path: Path, *, title: str | None = None
) -> Path | None:
    """감성 분포 (도넛) - 보너스."""
    if not counts:
        log.info("감성 분석 결과가 없어 감성 차트를 건너뜁니다.")
        return None
    setup_korean_font(config)

    labels = [c[0] for c in counts]
    values = [c[1] for c in counts]
    colors = [SENTIMENT_COLORS.get(label, MUTED) for label in labels]
    total = sum(values) or 1

    fig, ax = plt.subplots(figsize=(7.5, 6))
    fig.patch.set_facecolor("white")
    wedges, _ = ax.pie(
        values, colors=colors, startangle=90, counterclock=False,
        wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 2},
    )
    ax.axis("equal")
    ax.set_title(title or "뉴스 감성 분포", fontsize=14, color=INK, pad=16, loc="left")
    ax.text(0, 0, f"{total:,}건", ha="center", va="center", fontsize=16, color=INK)
    ax.legend(
        wedges,
        [f"{label}  {value:,}건 ({value / total:.0%})" for label, value in zip(labels, values)],
        loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=11,
        labelcolor=INK,
    )

    return _save(fig, out_path, int(config.get("chart.dpi", 130)))


# ------------------------------------------------------------------ 일괄 생성
def generate_charts(config, storage, *, prefix: str = "", **filters) -> dict[str, Any]:
    """리포트에 쓰는 차트를 한 번에 생성하고 경로 목록을 돌려준다."""
    chart_dir = config.path("paths.chart_dir", mkdir=True, is_dir=True)
    stamp = prefix or "latest"
    created: dict[str, Path] = {}

    category = chart_category_counts(
        config, storage.category_counts(**filters), chart_dir / f"{stamp}_category.png"
    )
    if category:
        created["category"] = category

    daily = chart_daily_trend(
        config, storage.daily_counts(**filters), chart_dir / f"{stamp}_daily.png"
    )
    if daily:
        created["daily"] = daily

    sentiment = chart_sentiment(
        config, storage.sentiment_counts(**filters), chart_dir / f"{stamp}_sentiment.png"
    )
    if sentiment:
        created["sentiment"] = sentiment

    return created

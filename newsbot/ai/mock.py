"""API 키가 없을 때 쓰는 규칙 기반 대체 구현 (오프라인 데모/테스트용).

실제 AI 호출과 **입출력 형태를 동일하게** 맞춰 두었기 때문에, 환경변수에 API 키만 넣으면
호출부 수정 없이 그대로 실제 LLM 결과로 바뀐다. 결과에는 항상 `[mock]` 표시를 남긴다.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

from ..utils import split_sentences, tokenize, truncate

MOCK_LABEL = "mock-rule-based"

_POSITIVE = {
    "상승", "호조", "개선", "성장", "확대", "증가", "흑자", "회복", "돌파", "최대",
    "수출", "타결", "합의", "성공", "수상", "신기록", "완화", "기대", "활황", "강세",
}
_NEGATIVE = {
    "하락", "부진", "악화", "감소", "적자", "위기", "우려", "논란", "사고", "사망",
    "붕괴", "충돌", "제재", "파업", "리콜", "손실", "급락", "약세", "무산", "피해",
}


# ------------------------------------------------------------------------ 요약
def mock_summarize(title: str, content: str, max_chars: int = 200) -> str:
    """빈도 기반 추출 요약: 핵심 단어를 많이 포함한 문장을 원문 순서대로 고른다."""
    sentences = split_sentences(content)
    if not sentences:
        return truncate(content or title, max_chars)

    freq = Counter(tokenize(f"{title} {content}"))
    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        tokens = tokenize(sentence)
        if not tokens:
            continue
        score = sum(freq[t] for t in tokens) / (len(tokens) ** 0.5)
        score *= 1.3 if index == 0 else 1.0  # 리드 문장 가중
        scored.append((score, index, sentence))

    if not scored:
        return truncate(content, max_chars)

    scored.sort(key=lambda x: x[0], reverse=True)
    chosen: list[tuple[int, str]] = []
    length = 0
    for score, index, sentence in scored:
        if length + len(sentence) > max_chars and chosen:
            continue
        chosen.append((index, sentence))
        length += len(sentence) + 1
        if length >= max_chars:
            break

    chosen.sort(key=lambda x: x[0])
    summary = " ".join(s for _, s in chosen)
    return truncate(summary, max_chars)


# ------------------------------------------------------------------------ 분석
def mock_analyze(articles: Sequence[dict[str, Any]], top_k: int = 8) -> dict[str, Any]:
    """카테고리 분포 + 키워드 빈도로 인사이트 항목을 구성한다."""
    if not articles:
        return {
            "overview": "[mock] 분석할 기사가 없습니다.",
            "trends": [], "keywords": [], "comparison": [], "implications": [],
        }

    corpus = " ".join(f"{a.get('title', '')} {a.get('snippet', '')}" for a in articles)
    freq = Counter(tokenize(corpus))
    keywords = [word for word, _ in freq.most_common(top_k)]

    categories = Counter(a.get("category") or "미분류" for a in articles)
    dates = Counter(a.get("date") or "미상" for a in articles)
    top_cat, top_cat_n = categories.most_common(1)[0]
    busiest_day, busiest_n = dates.most_common(1)[0]

    trends = [
        f"[mock] '{kw}' 관련 보도가 {cnt}회 등장하며 기간 내 비중이 높습니다."
        for kw, cnt in freq.most_common(3)
    ]
    trends.append(
        f"[mock] 카테고리 기준으로는 '{top_cat}'가 {top_cat_n}건({top_cat_n / len(articles):.0%})으로 가장 많습니다."
    )

    comparison = [
        f"[mock] 공통점: 상위 키워드 {', '.join(keywords[:3]) or '없음'}가 여러 카테고리에서 함께 등장합니다.",
        "[mock] 차이점: " + ", ".join(f"{c} {n}건" for c, n in categories.most_common(4)),
        f"[mock] 보도량이 가장 많았던 날짜는 {busiest_day}({busiest_n}건)입니다.",
    ]

    implications = [
        f"[mock] '{keywords[0] if keywords else '주요 이슈'}' 축의 후속 보도를 계속 추적할 필요가 있습니다.",
        f"[mock] '{top_cat}' 카테고리에 수집이 편중돼 있어 소스/카테고리 확장을 검토할 만합니다.",
    ]

    return {
        "overview": (
            f"[mock] 총 {len(articles)}건을 규칙 기반으로 집계했습니다. "
            f"최다 카테고리 '{top_cat}', 최다 키워드 '{keywords[0] if keywords else '-'}'."
        ),
        "trends": trends,
        "keywords": keywords,
        "comparison": comparison,
        "implications": implications,
    }


# ------------------------------------------------------------------------ 감성
def mock_sentiment(title: str, content: str) -> dict[str, Any]:
    """감성 사전 기반 점수화(-1.0 ~ 1.0)."""
    text = f"{title} {content}"
    pos = sum(text.count(word) for word in _POSITIVE)
    neg = sum(text.count(word) for word in _NEGATIVE)
    total = pos + neg

    if total == 0:
        return {"sentiment": "중립", "score": 0.0, "reason": "[mock] 감성 단어가 발견되지 않았습니다."}

    score = round((pos - neg) / total, 2)
    if score > 0.2:
        label = "긍정"
    elif score < -0.2:
        label = "부정"
    else:
        label = "중립"
    return {
        "sentiment": label,
        "score": score,
        "reason": f"[mock] 긍정어 {pos}회 / 부정어 {neg}회 기준 판정.",
    }

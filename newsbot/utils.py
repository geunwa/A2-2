"""공통 유틸리티: 텍스트 정규화 / 날짜 파싱 / URL 정규화 / 해시 / 간이 형태소 토큰화."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

KST = timezone(timedelta(hours=9), name="KST")

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
DATE_FMT = "%Y-%m-%d"

# URL 정규화 시 제거할 추적/네비게이션 파라미터
_DROP_QUERY_KEYS = {
    "section", "site", "utm_source", "utm_medium", "utm_campaign",
    "utm_term", "utm_content", "cp", "from", "ref", "fbclid", "gclid",
}

_ZERO_WIDTH = re.compile("[\u200b-\u200f\ufeff\u2060]")
_MULTI_SPACE = re.compile("[ \t\u00a0\u3000]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_TAG = re.compile(r"<[^>]+>")

_ISO_LIKE = re.compile(
    r"(?P<y>\d{4})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})"
    r"(?:[ T](?P<H>\d{1,2}):(?P<M>\d{2})(?::(?P<S>\d{2}))?)?"
)
_KO_DATE = re.compile(r"(?P<y>\d{4})년\s*(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일")

# 간이 키워드 추출용 불용어 (AI 미사용 폴백 경로에서 쓰인다)
STOPWORDS = {
    "그리고", "그러나", "하지만", "때문에", "이번", "지난", "올해", "내년", "관련",
    "대한", "위해", "통해", "따라", "대해", "가운데", "경우", "다시", "지금", "현재",
    "이날", "오늘", "내일", "어제", "기자", "연합뉴스", "뉴스", "보도", "밝혔다",
    "말했다", "전했다", "나타났다", "예정이다", "것으로", "라고", "에서", "으로",
    "에게", "이라고", "하는", "했다", "한다", "된다", "있다", "없다", "우리", "그는",
    "이는", "또한", "가장", "모든", "다른", "새로운", "최근", "지역", "국내", "국외",
    "사진", "제공", "무단", "전재", "재배포", "금지", "저작권자", "송고",
}

_TOKEN = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z0-9]{1,}")

# 조사 근사 제거용 (긴 것부터 검사)
_PARTICLES = (
    "으로부터", "에서는", "에게서", "이라는", "라는", "으로써", "으로서", "까지",
    "부터", "에서", "에게", "한테", "으로", "이라", "보다", "처럼", "만큼",
    "는", "은", "이", "가", "을", "를", "에", "의", "도", "와", "과", "로", "만",
)


# ------------------------------------------------------------------ 텍스트
def strip_html(value: str) -> str:
    """HTML 태그와 엔티티를 제거한 평문을 돌려준다."""
    if not value:
        return ""
    text = _TAG.sub(" ", value)
    return html.unescape(text)


def normalize_text(value: str | None, *, keep_newlines: bool = True) -> str:
    """텍스트 정규화: 유니코드 NFC, 제로폭 제거, 공백 압축, 양끝 정리."""
    if not value:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    text = html.unescape(text)
    text = _ZERO_WIDTH.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not keep_newlines:
        text = text.replace("\n", " ")
    text = _MULTI_SPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def truncate(value: str, limit: int, suffix: str = "…") -> str:
    """limit 글자로 자른다(자를 때만 suffix 를 붙인다)."""
    if not value:
        return ""
    if limit <= 0 or len(value) <= limit:
        return value
    return value[: max(0, limit - len(suffix))].rstrip() + suffix


def split_sentences(text: str) -> list[str]:
    """한국어/영어 혼용 문장 분리(간이)."""
    if not text:
        return []
    parts = re.split(r"(?<=[.!?。])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def strip_particle(token: str) -> str:
    """한국어 조사를 간단히 떼어낸다(형태소 분석기 없이 쓰는 근사 규칙).

    잘라낸 뒤 2글자 미만이 되면 원형을 유지해 과도한 절단을 막는다.
    """
    for particle in _PARTICLES:
        if token.endswith(particle) and len(token) - len(particle) >= 2:
            return token[: -len(particle)]
    return token


def tokenize(text: str) -> list[str]:
    """불용어/조사를 제거한 2글자 이상 토큰 목록 (간이 키워드 추출용)."""
    if not text:
        return []
    tokens = []
    for raw in _TOKEN.findall(text):
        token = strip_particle(raw.strip())
        if len(token) < 2 or token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        tokens.append(token)
    return tokens


# ------------------------------------------------------------------ URL
def normalize_url(url: str | None) -> str:
    """중복 판정을 위해 URL 을 정규화한다(추적 파라미터/프래그먼트 제거)."""
    if not url:
        return ""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if k.lower() not in _DROP_QUERY_KEYS]
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))


def make_hash(*values: str) -> str:
    """중복 판정 키(SHA-1 hex)."""
    joined = "".join((v or "").strip().lower() for v in values)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def url_hash(url: str) -> str:
    return make_hash(normalize_url(url))


# ------------------------------------------------------------------ 날짜
def now_kst() -> datetime:
    return datetime.now(KST)


def now_str() -> str:
    return now_kst().strftime(DATETIME_FMT)


def parse_datetime(value: str | datetime | None) -> datetime | None:
    """RSS(RFC822) / ISO8601 / '2026-08-18 10:30' / '2026년 8월 18일' 을 모두 받는다."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=KST)

    text = str(value).strip()
    if not text:
        return None

    # 1) RFC 822 (RSS pubDate)
    if "," in text and any(d in text for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
        try:
            dt = parsedate_to_datetime(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=KST)
        except (TypeError, ValueError):
            pass

    # 2) ISO 8601
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=KST)
    except ValueError:
        pass

    # 3) 한국어 날짜 표기
    m = _KO_DATE.search(text)
    if m:
        return datetime(int(m["y"]), int(m["m"]), int(m["d"]), tzinfo=KST)

    # 4) 느슨한 숫자 날짜
    m = _ISO_LIKE.search(text)
    if m:
        return datetime(
            int(m["y"]), int(m["m"]), int(m["d"]),
            int(m["H"] or 0), int(m["M"] or 0), int(m["S"] or 0), tzinfo=KST,
        )
    return None


def to_kst_string(value: str | datetime | None) -> str | None:
    """날짜 형식을 'YYYY-MM-DD HH:MM:SS' (KST) 로 통일한다."""
    dt = parse_datetime(value)
    if dt is None:
        return None
    return dt.astimezone(KST).strftime(DATETIME_FMT)


def to_date_string(value: str | datetime | None) -> str | None:
    """'YYYY-MM-DD' 만 돌려준다."""
    dt = parse_datetime(value)
    if dt is None:
        return None
    return dt.astimezone(KST).strftime(DATE_FMT)


def validate_date_arg(value: str, *, field: str) -> str:
    """CLI 날짜 옵션 검증. 'YYYY-MM-DD' 로 정규화해 돌려준다."""
    parsed = to_date_string(value)
    if not parsed:
        raise ValueError(f"{field} 날짜 형식이 올바르지 않습니다: {value} (예: 2026-08-18)")
    return parsed


def compression_ratio(before: int, after: int) -> float:
    """요약 압축률(%) — 낮을수록 많이 줄인 것."""
    if before <= 0:
        return 0.0
    return round(after / before * 100, 1)

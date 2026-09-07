"""기사 상세 페이지 HTML 파서 (BeautifulSoup).

RSS 수집기와 크롤링 수집기가 함께 사용한다.
- RSS 의 description 은 한 줄 요약뿐이라, AI 요약을 하려면 본문이 필요하다.
- 본문 영역 선택자 / 제거할 문단 클래스·패턴은 config.json 의 소스 설정에서 읽는다.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from ..logger import get_logger
from ..utils import normalize_text

log = get_logger("collectors.article")


def _meta(soup: BeautifulSoup, *, prop: str | None = None, name: str | None = None) -> str | None:
    tag = None
    if prop:
        tag = soup.find("meta", attrs={"property": prop})
    if tag is None and name:
        tag = soup.find("meta", attrs={"name": name})
    value = tag.get("content") if tag else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def extract_article(html: str, source_cfg: dict[str, Any]) -> dict[str, Any]:
    """기사 HTML 에서 제목/본문/작성일/기자/설명을 뽑아낸다.

    파싱에 실패하면 빈 문자열을 담아 돌려준다(정제 단계에서 걸러진다).
    """
    soup = BeautifulSoup(html, "lxml")

    title = _meta(soup, prop="og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    title = re.sub(r"\s*\|\s*[^|]+$", "", title or "").strip()  # ' | 연합뉴스' 꼬리 제거

    description = _meta(soup, prop="og:description") or _meta(soup, name="description") or ""
    published = (
        _meta(soup, prop="article:published_time")
        or _meta(soup, name="article:published_time")
        or _meta(soup, prop="og:regDate")
    )
    author = _meta(soup, prop="dable:author") or _meta(soup, name="author") or ""

    body_node = None
    for selector in source_cfg.get("article_selectors", ["article"]):
        body_node = soup.select_one(selector)
        if body_node is not None:
            break

    content = ""
    if body_node is not None:
        content = _extract_paragraphs(body_node, source_cfg)
    else:
        log.warning("본문 영역을 찾지 못했습니다(선택자 미일치).")

    if not published:
        # 메타 태그가 없으면 본문 하단의 '송고 2026-08-18 10:30' 같은 표기를 찾는다.
        stamp = soup.select_one("p.update-time, span.txt-time, .txt-time01")
        if stamp:
            published = stamp.get_text(" ", strip=True)

    return {
        "title": normalize_text(title, keep_newlines=False),
        "content": content,
        "description": normalize_text(description, keep_newlines=False),
        "published_at": published,
        "author": normalize_text(author, keep_newlines=False),
    }


def _extract_paragraphs(node, source_cfg: dict[str, Any]) -> str:
    drop_classes = set(source_cfg.get("drop_paragraph_classes", []))
    patterns = [re.compile(p) for p in source_cfg.get("drop_paragraph_patterns", [])]

    paragraphs: list[str] = []
    for tag in node.find_all("p"):
        classes = set(tag.get("class") or [])
        if classes & drop_classes:
            continue
        text = normalize_text(tag.get_text(" ", strip=True), keep_newlines=False)
        if not text:
            continue
        if any(p.search(text) for p in patterns):
            continue
        paragraphs.append(text)

    if not paragraphs:  # <p> 구조가 아닌 경우의 폴백
        text = normalize_text(node.get_text("\n", strip=True))
        return text

    return "\n".join(paragraphs)


def extract_links(html: str, base_url: str, selector: str) -> list[dict[str, str]]:
    """목록 페이지에서 기사 링크와 제목을 뽑는다."""
    from urllib.parse import urljoin

    soup = BeautifulSoup(html, "lxml")
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.select(selector):
        href = anchor.get("href")
        if not href:
            continue
        url = urljoin(base_url, href.strip())
        if url in seen:
            continue
        seen.add(url)
        items.append({
            "url": url,
            "title": normalize_text(anchor.get_text(" ", strip=True), keep_newlines=False),
        })
    return items

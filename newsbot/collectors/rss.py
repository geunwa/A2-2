"""수집 방법 1 — RSS 피드(공개 API 대체) 수집기.

장점: 서버에서 제공하는 구조화된 데이터를 파싱해 정확하고,
      속도가 빠르며 본문을 가져오면 풍부한 데이터를 얻을 수 있다.
단점: 제공하는 필드가 제한적이어서 본문 내용이 없다.
      (기본값은 옵션으로 본문까지 추가로 가져와 보완)
"""

from __future__ import annotations

import math
from typing import Any

from bs4 import BeautifulSoup, Tag

from ..logger import get_logger
from ..utils import normalize_text, now_str, strip_html, url_hash
from .article import extract_article
from .base import CollectResult
from .http_client import FetchError, HttpClient

log = get_logger("collectors.rss")

METHOD = "rss"


class RssCollector:
    """RSS 피드에서 뉴스 기사 데이터를 수집한다."""

    method = METHOD

    def __init__(self, config, http: HttpClient, source_key: str | None = None):
        self.config = config
        self.http = http
        self.source_cfg = config.source(source_key)
        self.source_key = self.source_cfg["key"]
        self.source_name = self.source_cfg.get("name", self.source_key)

    # ------------------------------------------------------------------ 공개
    def available_categories(self) -> list[str]:
        return list(self.source_cfg.get("categories", {}).keys())

    def collect(
        self,
        categories: list[str] | None = None,
        limit: int = 20,
        *,
        with_content: bool = True,
    ) -> CollectResult:
        """카테고리별 RSS 를 순회해 지정 개수만큼 레코드를 수집한다."""
        result = CollectResult(method=self.method, source=self.source_key)
        cats = (
            categories
            or self.source_cfg.get("default_categories")
            or self.available_categories()
        )
        cats = [c for c in cats if c]
        if not cats:
            log.error("수집할 카테고리가 없습니다.")
            return result

        per_category = max(1, math.ceil(limit / len(cats)))
        template = self.source_cfg.get("rss_template")
        slugs = self.source_cfg.get("categories", {})

        for category in cats:
            if len(result.records) >= limit:
                break
            slug = slugs.get(category)
            if not slug:
                log.warning("알 수 없는 카테고리를 건너뜁니다: %s", category)
                result.add_error(f"unknown category: {category}")
                continue

            feed_url = template.format(slug=slug)
            log.info("RSS 수집: %s (%s)", category, feed_url)
            try:
                resp = self.http.get(feed_url, check_robots=False)
            except FetchError as exc:
                log.error("RSS 수집 실패 [%s]: %s", category, exc)
                result.add_error(f"{category}: {exc}")
                continue

            entries = self._parse_feed(resp.content)
            if not entries:
                log.warning("RSS 항목이 비어 있습니다: %s", feed_url)

            taken = 0
            for entry in entries:
                if taken >= per_category or len(result.records) >= limit:
                    break
                record = self._to_record(entry, category, feed_url)
                if record is None:
                    result.add_error(f"{category}: link 없는 항목")
                    continue
                if with_content:
                    self._enrich_with_body(record, result)
                result.records.append(record)
                result.succeeded += 1
                taken += 1

            log.info("RSS 수집 [%s]: %d건", category, taken)

        return result

    # ------------------------------------------------------------------ 내부
    @staticmethod
    def _text_of(item: Tag, tag_name: str) -> str:
        """item 태그에서 tag_name 텍스트를 추출한다. 없으면 빈 문자열 반환."""
        node = item.find(tag_name)
        return node.get_text(strip=True) if node else ""

    @staticmethod
    def _parse_feed(payload: bytes) -> list[dict[str, str]]:
        """RSS XML 을 dict 목록으로 변환한다."""
        soup = BeautifulSoup(payload, "xml")
        entries: list[dict[str, str]] = []

        # ✅ 수정: text_of 를 루프 밖 정적 메서드로 분리
        #    변경 전: 루프 안에서 매 순회마다 함수 객체를 새로 생성
        #    변경 후: _text_of(item, tag_name) 형태로 item 을 인자로 전달
        text_of = RssCollector._text_of
        for item in soup.find_all("item"):
            entries.append({
                "title":         text_of(item, "title"),
                "link":          text_of(item, "link") or text_of(item, "guid"),
                "pub_date":      text_of(item, "pubDate"),
                "author":        text_of(item, "creator") or text_of(item, "author"),
                "description":   strip_html(text_of(item, "description")),
                "feed_category": text_of(item, "category"),
            })
        return entries

    def _to_record(
        self, entry: dict[str, str], category: str, feed_url: str
    ) -> dict[str, Any] | None:
        link = entry.get("link", "").strip()
        if not link:
            return None
        payload = {
            "title": normalize_text(entry.get("title"), keep_newlines=False),
            "link": link,
            "pub_date": entry.get("pub_date"),
            "author": entry.get("author"),
            "description": normalize_text(
                entry.get("description"), keep_newlines=False
            ),
            "category": category,
            "content": "",
        }
        return {
            "source": self.source_key,
            "source_name": self.source_name,
            "collect_method": self.method,
            "origin_url": feed_url,
            "url": link,
            "url_hash": url_hash(link),
            "category": category,
            "collected_at": now_str(),
            "payload": payload,
        }

    def _enrich_with_body(
        self, record: dict[str, Any], result: CollectResult
    ) -> None:
        """본문 보완을 위해 기사 페이지를 1회 추가 수집한다(실패해도 계속 진행)."""
        url = record["url"]
        try:
            resp = self.http.get(url)
        except FetchError as exc:
            log.warning("본문 수집 실패(선택적 처리): %s (%s)", url, exc)
            result.add_body_error(f"body: {url}: {exc}")
            return
        try:
            parsed = extract_article(resp.text, self.source_cfg)
        except Exception as exc:
            log.warning("본문 파싱 실패: %s (%s)", url, exc)
            result.add_body_error(f"parse: {url}: {exc}")
            return

        payload = record["payload"]
        payload["content"] = parsed.get("content", "")
        payload["author"] = payload.get("author") or parsed.get("author")
        payload["pub_date"] = payload.get("pub_date") or parsed.get("published_at")
        if parsed.get("title"):
            payload["title"] = payload.get("title") or parsed["title"]
"""수집 방법 2 — 뉴스 사이트 HTML 크롤링 수집기 (BeautifulSoup).

장점: 피드가 제공하지 않는 **본문 전문·기자명·상세 메타**까지 확보할 수 있고,
      RSS 를 제공하지 않는 사이트에도 적용 가능하다.
단점: HTML 구조 변경에 취약하고, 요청 수가 많아 서버 부담·차단 위험이 있으며
      robots.txt/이용약관 등 **정책 준수와 요청 간 지연**이 필수다.

정책 준수 사항
- robots.txt 를 확인해 허용된 URL 만 요청한다 (config: http.respect_robots).
- 요청 사이에 최소 지연(config: http.request_delay_sec)을 강제한다.
- 목록 1페이지만 읽고, 요청 수를 --limit 로 제한한다.
"""

from __future__ import annotations

import math
from typing import Any

from ..logger import get_logger
from ..utils import normalize_text, now_str, url_hash
from .article import extract_article, extract_links
from .base import CollectResult
from .http_client import FetchError, HttpClient

log = get_logger("collectors.crawl")

METHOD = "crawl"


class CrawlCollector:
    """뉴스 목록 페이지 → 기사 상세 페이지를 순차 크롤링한다."""

    method = METHOD

    def __init__(self, config, http: HttpClient, source_key: str | None = None):
        self.config = config
        self.http = http
        self.source_cfg = config.source(source_key)
        self.source_key = self.source_cfg["key"]
        self.source_name = self.source_cfg.get("name", self.source_key)

    def available_categories(self) -> list[str]:
        rss_only = set(self.source_cfg.get("rss_only_categories", []))
        return [c for c in self.source_cfg.get("categories", {}) if c not in rss_only]

    def collect(
        self,
        categories: list[str] | None = None,
        limit: int = 20,
        *,
        # ✅ 수정: **_ 대신 with_content 명시 — rss.py 와 인터페이스 통일
        #    변경 전: def collect(..., **_)
        #    변경 후: def collect(..., *, with_content: bool = True)
        with_content: bool = True,
    ) -> CollectResult:
        result = CollectResult(method=self.method, source=self.source_key)
        cats = (
            categories
            or self.source_cfg.get("default_categories")
            or self.available_categories()
        )
        rss_only = set(self.source_cfg.get("rss_only_categories", []))
        cats = [c for c in cats if c and c not in rss_only]
        if not cats:
            log.error("크롤링 가능한 카테고리가 없습니다.")
            return result

        per_category = max(1, math.ceil(limit / len(cats)))
        template = self.source_cfg.get("list_template")
        selector = self.source_cfg.get("list_link_selector", "a")
        slugs = self.source_cfg.get("categories", {})

        for category in cats:
            if len(result.records) >= limit:
                break
            slug = slugs.get(category)
            if not slug:
                log.warning("알 수 없는 카테고리라 건너뜁니다: %s", category)
                result.add_error(f"unknown category: {category}")
                continue

            list_url = template.format(slug=slug)
            log.info("목록 페이지 크롤링: %s (%s)", category, list_url)
            try:
                resp = self.http.get(list_url)
            except FetchError as exc:
                log.error("목록 페이지 수집 실패 [%s]: %s", category, exc)
                result.add_error(f"{category}: {exc}")
                continue

            links = extract_links(resp.text, list_url, selector)
            if not links:
                log.warning("목록에서 기사 링크를 찾지 못했습니다: %s", list_url)

            taken = 0
            for link in links:
                if taken >= per_category or len(result.records) >= limit:
                    break
                record = self._fetch_article(link, category, list_url, result)
                if record is None:
                    continue
                result.records.append(record)
                result.succeeded += 1
                taken += 1

            log.info("크롤링 수집 [%s]: %d건", category, taken)

        return result

    # ------------------------------------------------------------------ 내부
    def _fetch_article(
        self, link: dict[str, str], category: str, origin_url: str, result: CollectResult
    ) -> dict[str, Any] | None:
        url = link["url"]
        if not self.http.is_allowed(url):
            log.warning("robots.txt 로 차단된 기사라 건너뜁니다: %s", url)
            result.add_error(f"robots blocked: {url}")
            return None

        try:
            resp = self.http.get(url)
        except FetchError as exc:
            log.error("기사 수집 실패: %s (%s)", url, exc)
            result.add_error(f"{url}: {exc}")          # HTTP 실패 → failed
            return None

        try:
            parsed = extract_article(resp.text, self.source_cfg)
        except Exception as exc:
            log.error("기사 파싱 실패: %s (%s)", url, exc)
            # ✅ 수정: 파싱 실패는 add_body_error() — rss.py 와 동일 패턴
            #    변경 전: result.add_error(f"parse: {url}: {exc}")  → failed += 1
            #    변경 후: result.add_body_error(...)                → body_failed += 1
            result.add_body_error(f"parse: {url}: {exc}")
            return None

        payload = {
            "title": parsed.get("title") or normalize_text(
                link.get("title"), keep_newlines=False
            ),
            "link": url,
            "pub_date": parsed.get("published_at"),
            "author": parsed.get("author"),
            "description": parsed.get("description"),
            "content": parsed.get("content", ""),
            "category": category,
            "list_title": link.get("title"),
        }
        return {
            "source": self.source_key,
            "source_name": self.source_name,
            "collect_method": self.method,
            "origin_url": origin_url,
            "url": url,
            "url_hash": url_hash(url),
            "category": category,
            "collected_at": now_str(),
            "payload": payload,
        }
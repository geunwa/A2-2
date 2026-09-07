"""뉴스 수집기 패키지.

- ``rss.py``     : 방법 1 — 공개 RSS/API 피드 수집 (구조화된 데이터, 빠르고 안정적)
- ``crawler.py`` : 방법 2 — 뉴스 사이트 HTML 크롤링 (BeautifulSoup, 본문 전체 확보)
- ``http_client.py`` : 두 방식이 공유하는 HTTP 계층 (타임아웃/재시도/요청 지연/robots)
"""

from .http_client import FetchError, HttpClient
from .rss import RssCollector
from .crawler import CrawlCollector

__all__ = ["FetchError", "HttpClient", "RssCollector", "CrawlCollector"]

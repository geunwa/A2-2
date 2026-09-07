"""HTTP 요청 공통 계층.

수집 방식(RSS/크롤링)에 상관없이 아래를 한 곳에서 책임진다.

* **타임아웃**       : 모든 요청에 connect/read 타임아웃을 건다.
* **오류 처리/재시도**: 타임아웃·연결오류·5xx·429 는 지수 백오프로 재시도, 4xx 는 즉시 실패.
* **요청 간 지연**    : 과도한 요청을 막기 위해 도메인 단위로 최소 간격을 강제한다.
* **robots.txt 준수** : 크롤링 대상 경로가 허용되는지 확인한다.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from ..logger import get_logger

log = get_logger("http")


class FetchError(Exception):
    """HTTP 수집 실패(재시도 후에도 실패했거나, 정책상 요청 불가)."""


class HttpClient:
    """requests.Session 래퍼."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff_sec: float = 1.5,
        request_delay_sec: float = 1.0,
        user_agent: str = "NewsBot/1.0",
        respect_robots: bool = True,
    ):
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))
        self.backoff_sec = float(backoff_sec)
        self.request_delay_sec = max(0.0, float(request_delay_sec))
        self.respect_robots = bool(respect_robots)
        self.user_agent = user_agent

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        })

        self._lock = threading.Lock()
        self._last_request_at: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    # ------------------------------------------------------------ 설정 팩토리
    @classmethod
    def from_config(cls, config) -> "HttpClient":
        return cls(
            timeout=config.get("http.timeout", 10),
            max_retries=config.get("http.max_retries", 2),
            backoff_sec=config.get("http.backoff_sec", 1.5),
            request_delay_sec=config.get("http.request_delay_sec", 1.0),
            user_agent=config.get("http.user_agent", "NewsBot/1.0"),
            respect_robots=config.get("http.respect_robots", True),
        )

    # ------------------------------------------------------------ 요청 간 지연
    def _throttle(self, host: str) -> None:
        if self.request_delay_sec <= 0:
            return
        with self._lock:
            last = self._last_request_at.get(host, 0.0)
            wait = self.request_delay_sec - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at[host] = time.monotonic()

    # ------------------------------------------------------------ robots.txt
    def _robot_parser(self, url: str) -> RobotFileParser | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]

        parser: RobotFileParser | None = None
        try:
            resp = self.session.get(f"{origin}/robots.txt", timeout=self.timeout)
            if resp.status_code == 200:
                parser = RobotFileParser()
                parser.parse(resp.text.splitlines())
                log.debug("robots.txt 확인: %s", origin)
            else:
                log.warning("robots.txt 응답 %s (%s) - 허용으로 간주", resp.status_code, origin)
        except requests.RequestException as exc:
            log.warning("robots.txt 조회 실패(%s): %s - 허용으로 간주", origin, exc)

        self._robots[origin] = parser
        return parser

    def is_allowed(self, url: str) -> bool:
        """robots.txt 기준으로 요청 가능한 URL 인지 확인한다."""
        if not self.respect_robots:
            return True
        parser = self._robot_parser(url)
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    # ------------------------------------------------------------------ 요청
    def get(self, url: str, *, check_robots: bool = True, **kwargs) -> requests.Response:
        """GET 요청. 실패 시 FetchError 를 던진다."""
        if check_robots and not self.is_allowed(url):
            raise FetchError(f"robots.txt 정책상 수집이 허용되지 않는 URL 입니다: {url}")

        host = urlsplit(url).netloc
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._throttle(host)
            try:
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
            except requests.Timeout as exc:
                last_error = exc
                log.warning("타임아웃(%s/%s): %s", attempt + 1, self.max_retries + 1, url)
            except requests.RequestException as exc:
                last_error = exc
                log.warning("요청 실패(%s/%s): %s (%s)", attempt + 1, self.max_retries + 1, url, exc)
            else:
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = FetchError(f"HTTP {resp.status_code}")
                    log.warning("일시적 오류 HTTP %s (%s/%s): %s",
                                resp.status_code, attempt + 1, self.max_retries + 1, url)
                else:
                    raise FetchError(f"HTTP {resp.status_code}: {url}")

            if attempt < self.max_retries:
                time.sleep(self.backoff_sec * (2 ** attempt))

        raise FetchError(f"요청 실패({self.max_retries + 1}회 시도): {url} ({last_error})")

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

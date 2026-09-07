"""설정 로딩 모듈.

- 설정 파일(config.json)에서 뉴스 소스 URL, 중복 정책, AI 모델 등을 읽는다.
- API 키는 **절대 설정 파일/코드에 직접 쓰지 않는다.** 설정에는 환경변수 '이름'만 두고,
  실제 값은 os.environ 에서 읽는다. (.env 파일도 지원)
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

# 프로젝트 루트 = 이 파일(newsbot/config.py)의 상위의 상위 디렉터리
BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG_FILENAME = "config.json"

#: config.json 에 값이 없을 때 사용하는 기본값(구조적 폴백).
#: 'sources' 는 기본값을 두지 않는다 - 반드시 설정 파일로 관리한다.
DEFAULTS: dict[str, Any] = {
    "app": {"name": "NewsBot"},
    "paths": {
        "db": "data/newsbot.db",
        "output_dir": "output",
        "chart_dir": "output/charts",
        "export_dir": "output/exports",
        "report_dir": "output/reports",
        "log_dir": "logs",
    },
    "http": {
        "timeout": 10,
        "max_retries": 2,
        "backoff_sec": 1.5,
        "request_delay_sec": 1.0,
        "user_agent": "NewsBot/1.0",
        "respect_robots": True,
    },
    "cleaning": {
        "on_duplicate": "skip",
        "required_fields": ["title", "url", "content"],
        "min_content_length": 60,
        "min_title_length": 5,
        "missing_category": "미분류",
        "missing_author": "미상",
        "content_fallback_to_description": True,
        "max_content_length": 20000,
    },
    "ai": {
        "provider": "auto",
        "fallback_to_mock": True,
        "timeout": 60,
        "max_retries": 2,
        "backoff_sec": 2.0,
        "providers": {},
        "summary": {"max_chars": 200, "max_input_chars": 4000, "skip_if_summarized": True},
        "analyze": {"max_articles": 60, "snippet_chars": 350},
        "sentiment": {"max_input_chars": 1200},
    },
    "report": {"top_n": 5, "format": "md", "include_charts": True},
    "chart": {
        "font_candidates": ["Malgun Gothic", "NanumGothic", "Noto Sans KR", "AppleGothic"],
        "dpi": 130,
        "figsize": [10, 6],
    },
    "logging": {
        "level": "INFO",
        "file": "logs/newsbot.log",
        "console": True,
        "max_bytes": 2000000,
        "backup_count": 3,
    },
}


class ConfigError(Exception):
    """설정 파일이 없거나 잘못되었을 때 발생."""


def _deep_merge(base: dict, override: dict) -> dict:
    """override 값으로 base 를 재귀 병합한 새 dict 를 돌려준다."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_dotenv(path: Path) -> None:
    """의존성 없이 .env 파일을 읽어 os.environ 에 채운다(기존 환경변수 우선)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


class Config:
    """점 표기법('ai.summary.max_chars')으로 접근하는 얇은 설정 래퍼."""

    def __init__(self, data: dict[str, Any], source_path: Path | None = None):
        self._data = data
        self.source_path = source_path
        self.base_dir = BASE_DIR

    # ------------------------------------------------------------------ 조회
    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, dotted_key: str) -> Any:
        value = self.get(dotted_key, _MISSING)
        if value is _MISSING:
            raise KeyError(dotted_key)
        return value

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    # ------------------------------------------------------------------ 경로
    def path(self, dotted_key: str, *, mkdir: bool = False, is_dir: bool = False) -> Path:
        """설정의 상대 경로를 프로젝트 루트 기준 절대 경로로 바꾼다."""
        raw = self.get(dotted_key)
        if raw is None:
            raise ConfigError(f"경로 설정이 없습니다: {dotted_key}")
        p = Path(raw)
        if not p.is_absolute():
            p = self.base_dir / p
        if mkdir:
            (p if is_dir else p.parent).mkdir(parents=True, exist_ok=True)
        return p

    # ------------------------------------------------------------------ 소스
    def source(self, name: str | None = None) -> dict[str, Any]:
        """뉴스 소스 설정 블록을 돌려준다."""
        sources = self.get("sources", {}) or {}
        key = name or sources.get("default")
        if not key:
            raise ConfigError("설정에 sources.default 가 없습니다.")
        block = sources.get(key)
        if not isinstance(block, dict):
            available = [k for k in sources if k != "default"]
            raise ConfigError(f"알 수 없는 뉴스 소스: {key} (사용 가능: {', '.join(available)})")
        return {**block, "key": key}

    def source_keys(self) -> list[str]:
        return [k for k in (self.get("sources", {}) or {}) if k != "default"]

    # ------------------------------------------------------------------ 비밀값
    def api_key_for(self, provider: str) -> str | None:
        """AI 제공자의 API 키를 환경변수에서 읽는다. 설정에는 키 값을 저장하지 않는다."""
        env_name = self.get(f"ai.providers.{provider}.api_key_env")
        if not env_name:
            return None
        value = os.environ.get(env_name, "").strip()
        return value or None


class _Missing:
    pass


_MISSING = _Missing()


def load_config(path: str | os.PathLike | None = None) -> Config:
    """설정 파일을 읽어 Config 객체를 만든다.

    Args:
        path: 설정 파일 경로. None 이면 프로젝트 루트의 config.json 을 쓴다.
    """
    _load_dotenv(BASE_DIR / ".env")

    cfg_path = Path(path) if path else BASE_DIR / DEFAULT_CONFIG_FILENAME
    if not cfg_path.is_absolute():
        cfg_path = BASE_DIR / cfg_path

    if not cfg_path.exists():
        raise ConfigError(
            f"설정 파일을 찾을 수 없습니다: {cfg_path}\n"
            f"config.example.json 을 복사해 config.json 을 만들어 주세요."
        )
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"설정 파일 JSON 파싱 실패: {cfg_path} ({exc})") from exc

    if not isinstance(raw, dict):
        raise ConfigError("설정 파일 최상위는 JSON 객체여야 합니다.")

    merged = _deep_merge(DEFAULTS, raw)
    if not merged.get("sources"):
        raise ConfigError("설정 파일에 'sources' 블록이 필요합니다.")
    return Config(merged, cfg_path)

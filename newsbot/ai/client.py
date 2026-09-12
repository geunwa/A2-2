"""AI API 호출 공통 계층.

지원 제공자(설정 ``ai.providers``): ``gemini`` / ``openai`` / ``anthropic``
- 세 제공자 모두 **requests 로 REST 엔드포인트를 직접 호출**한다.
  (과제 조건: "공식 SDK 또는 requests 직접 호출". 여기서는 제공자 교체가 쉬운 단일 계층을 택했다.)
- **API 키는 코드/설정 파일에 넣지 않는다.** 설정에는 환경변수 이름만 두고 값은 os.environ 에서 읽는다.
- 키가 하나도 없으면 ``mock`` 모드로 떨어져 규칙 기반 대체 구현(mock.py)이 동작한다.

AI 호출 흐름
    프롬프트 구성(system + user) → HTTP POST → 응답 본문에서 텍스트 추출 → 후처리(JSON 파싱 등)
    실패(타임아웃/4xx/5xx)는 재시도 후 AIError 로 올려 호출부에서 '로깅 후 스킵' 하게 한다.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests

from ..logger import get_logger

log = get_logger("ai.client")

PROVIDER_PRIORITY = ("gemini", "openai", "anthropic")
MOCK = "mock"


class AIError(Exception):
    """AI API 호출 실패."""


class AIClient:
    """제공자 중립 텍스트 생성 클라이언트."""

    def __init__(self, config, provider: str | None = None):
        self.config = config
        self.timeout = float(config.get("ai.timeout", 60))
        self.max_retries = max(0, int(config.get("ai.max_retries", 2)))
        self.backoff_sec = float(config.get("ai.backoff_sec", 2.0))
        self.provider = self._resolve_provider(provider or config.get("ai.provider", "auto"))
        self.provider_cfg = config.get(f"ai.providers.{self.provider}", {}) or {}
        self.model = self.provider_cfg.get("model", MOCK) if self.provider != MOCK else "mock-rule-based"
        self.api_key = config.api_key_for(self.provider) if self.provider != MOCK else None

        if self.provider == MOCK:
            log.warning(
                "AI API 키가 없어 mock(규칙 기반) 모드로 동작합니다. "
                "실제 AI 요약/분석을 쓰려면 환경변수에 API 키를 설정하세요: %s",
                ", ".join(self._key_env_names()) or "(설정된 제공자 없음)",
            )
        else:
            log.info("AI 제공자: %s (model=%s)", self.provider, self.model)

    # ------------------------------------------------------------------ 상태
    @property
    def is_mock(self) -> bool:
        return self.provider == MOCK

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    def _key_env_names(self) -> list[str]:
        providers = self.config.get("ai.providers", {}) or {}
        return [v.get("api_key_env") for v in providers.values() if v.get("api_key_env")]

    def _resolve_provider(self, requested: str) -> str:
        requested = (requested or "auto").lower()
        providers = self.config.get("ai.providers", {}) or {}

        if requested not in ("auto", MOCK):
            if requested not in providers:
                raise AIError(f"설정에 없는 AI 제공자입니다: {requested}")
            if not self.config.api_key_for(requested):
                env = providers[requested].get("api_key_env", "?")
                if self.config.get("ai.fallback_to_mock", True):
                    log.warning("%s API 키(%s)가 없어 mock 모드로 전환합니다.", requested, env)
                    return MOCK
                raise AIError(f"{requested} API 키가 없습니다. 환경변수 {env} 를 설정하세요.")
            return requested

        if requested == MOCK:
            return MOCK

        for name in (*PROVIDER_PRIORITY, *providers.keys()):
            if name in providers and self.config.api_key_for(name):
                return name

        if self.config.get("ai.fallback_to_mock", True):
            return MOCK
        raise AIError("사용 가능한 AI API 키가 없습니다. 환경변수를 설정하세요.")

    # ------------------------------------------------------------------ 호출
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        """프롬프트를 보내고 생성된 텍스트를 돌려준다. 실패 시 AIError."""
        if self.is_mock:
            raise AIError("mock 모드에서는 원격 호출을 하지 않습니다.")

        senders = {
            "gemini": self._call_gemini,
            "openai": self._call_openai,
            "anthropic": self._call_anthropic,
        }
        send = senders.get(self.provider)
        if send is None:
            raise AIError(f"지원하지 않는 제공자: {self.provider}")

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                text = send(prompt, system, max_tokens, temperature)
            except requests.Timeout as exc:
                last_error = exc
                log.warning("AI 요청 타임아웃 (%s/%s)", attempt + 1, self.max_retries + 1)
            except requests.RequestException as exc:
                last_error = exc
                log.warning("AI 요청 오류 (%s/%s): %s", attempt + 1, self.max_retries + 1, exc)
            except AIError as exc:
                if _is_retryable(str(exc)):
                    last_error = exc
                    log.warning("AI 일시적 오류 (%s/%s): %s", attempt + 1, self.max_retries + 1, exc)
                else:
                    raise
            else:
                if text and text.strip():
                    return text.strip()
                last_error = AIError("빈 응답")
                log.warning("AI 응답이 비어 있습니다 (%s/%s)", attempt + 1, self.max_retries + 1)

            if attempt < self.max_retries:
                time.sleep(self.backoff_sec * (2 ** attempt))

        raise AIError(f"AI 호출 실패({self.max_retries + 1}회 시도): {last_error}")

    # -------------------------------------------------------------- 제공자별
    def _endpoint(self) -> str:
        endpoint = self.provider_cfg.get("endpoint")
        if not endpoint:
            raise AIError(f"{self.provider} endpoint 설정이 없습니다.")
        return endpoint.replace("{model}", self.model)

    def _call_gemini(self, prompt: str, system: str | None, max_tokens: int, temperature: float) -> str:
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        resp = requests.post(
            self._endpoint(),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            json=body,
            timeout=self.timeout,
        )
        data = _json_or_error(resp, "gemini")
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(f"gemini 응답 파싱 실패: {exc}") from exc

    def _call_openai(self, prompt: str, system: str | None, max_tokens: int, temperature: float) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = requests.post(
            self._endpoint(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": messages,
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=self.timeout,
        )
        data = _json_or_error(resp, "openai")
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(f"openai 응답 파싱 실패: {exc}") from exc

    def _call_anthropic(self, prompt: str, system: str | None, max_tokens: int, temperature: float) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system

        resp = requests.post(
            self._endpoint(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": self.provider_cfg.get("api_version", "2023-06-01"),
            },
            json=body,
            timeout=self.timeout,
        )
        data = _json_or_error(resp, "anthropic")
        try:
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        except (AttributeError, TypeError) as exc:
            raise AIError(f"anthropic 응답 파싱 실패: {exc}") from exc


# ---------------------------------------------------------------------- 유틸
def _json_or_error(resp: requests.Response, provider: str) -> dict[str, Any]:
    if resp.status_code != 200:
        snippet = (resp.text or "")[:300].replace("\n", " ")
        raise AIError(f"{provider} HTTP {resp.status_code}: {snippet}")
    try:
        return resp.json()
    except ValueError as exc:
        raise AIError(f"{provider} 응답이 JSON 이 아닙니다: {exc}") from exc


def _is_retryable(message: str) -> bool:
    return any(code in message for code in ("429", "500", "502", "503", "504", "빈 응답"))


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """모델 응답에서 JSON 객체를 최대한 관대하게 뽑아낸다."""
    if not text:
        raise AIError("빈 응답에서 JSON 을 추출할 수 없습니다.")

    candidates = [m.group(1) for m in _JSON_BLOCK.finditer(text)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    candidates.append(text)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    raise AIError("응답에서 JSON 객체를 찾지 못했습니다.")


def resolve_env_hint(config) -> str:
    """설정에 정의된 API 키 환경변수 이름 안내 문자열."""
    providers = config.get("ai.providers", {}) or {}
    parts = []
    for name, cfg in providers.items():
        env = cfg.get("api_key_env")
        if env and not os.environ.get(env):   # 키가 없는 제공자만 포함
            parts.append(f"{name}={env}")
    return ", ".join(parts)

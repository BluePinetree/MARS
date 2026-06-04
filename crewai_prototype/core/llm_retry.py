"""
core/llm_retry.py
=================
LLM 호출 래퍼: 재시도 정책 + 오류 분류 + 비용 추적 (P1-1, P3-2).

모든 직접 litellm.completion 호출을 이 모듈의 call_with_retry()를 통해 실행한다.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class LLMErrorKind(Enum):
    RATE_LIMIT = "rate_limit"       # 429 → 지수 백오프 후 재시도
    AUTH = "auth"                   # 401/403 → 재시도 불가
    TOKEN_LIMIT = "token_limit"     # 400 context too long → 재시도 불가
    NETWORK = "network"             # timeout/connection → 즉시 재시도
    SERVER = "server"               # 5xx → 짧은 대기 후 재시도
    UNKNOWN = "unknown"             # 분류 불가 → 1회 재시도


def classify_llm_error(exc: Exception) -> LLMErrorKind:
    msg = str(exc).lower()
    # litellm / openai 오류 코드 우선 탐지
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if status:
        if status == 429:
            return LLMErrorKind.RATE_LIMIT
        if status in (401, 403):
            return LLMErrorKind.AUTH
        if status == 400 and any(k in msg for k in ("token", "context", "too long", "max")):
            return LLMErrorKind.TOKEN_LIMIT
        if 500 <= status < 600:
            return LLMErrorKind.SERVER
    # 문자열 패턴 폴백
    if any(k in msg for k in ("rate limit", "rate_limit", "429", "quota")):
        return LLMErrorKind.RATE_LIMIT
    if any(k in msg for k in ("unauthorized", "invalid api key", "auth", "403", "401")):
        return LLMErrorKind.AUTH
    if any(k in msg for k in ("context length", "token", "too long", "max_tokens")):
        return LLMErrorKind.TOKEN_LIMIT
    if any(k in msg for k in ("timeout", "connection", "network", "read error")):
        return LLMErrorKind.NETWORK
    if any(k in msg for k in ("500", "502", "503", "504", "server error", "service unavailable")):
        return LLMErrorKind.SERVER
    return LLMErrorKind.UNKNOWN


# 재시도 불가 오류 종류
_NO_RETRY = {LLMErrorKind.AUTH, LLMErrorKind.TOKEN_LIMIT}

# 오류 종류별 초기 대기(초)
_BASE_WAIT: dict[LLMErrorKind, float] = {
    LLMErrorKind.RATE_LIMIT: 20.0,
    LLMErrorKind.NETWORK: 2.0,
    LLMErrorKind.SERVER: 5.0,
    LLMErrorKind.UNKNOWN: 3.0,
}


def call_with_retry(
    model: str,
    messages: list[dict],
    api_key: str,
    temperature: float = 0.0,
    max_completion_tokens: int = 1024,
    max_attempts: int = 3,
    on_retry: Callable[[int, LLMErrorKind, float], None] | None = None,
    **kwargs: Any,
) -> Any:
    """
    litellm.completion 을 재시도 정책과 함께 호출한다.

    on_retry(attempt, error_kind, wait_secs): 재시도 전 콜백 (로깅/이벤트 발행용).
    반환값: litellm Response 객체.
    """
    import litellm  # 지연 임포트

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = litellm.completion(
                model=model,
                messages=messages,
                api_key=api_key,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
                **kwargs,
            )
            _cost_tracker.record(resp)
            return resp
        except Exception as exc:
            kind = classify_llm_error(exc)
            last_exc = exc

            if kind in _NO_RETRY:
                logger.error("[LLMRetry] 재시도 불가 오류 (%s): %s", kind.value, exc)
                raise

            if attempt >= max_attempts:
                logger.error("[LLMRetry] %d회 시도 소진 (%s): %s", max_attempts, kind.value, exc)
                raise

            wait = _BASE_WAIT.get(kind, 3.0) * (2 ** (attempt - 1))  # 지수 백오프
            logger.warning(
                "[LLMRetry] 시도 %d/%d — %s, %.1fs 대기 후 재시도: %s",
                attempt, max_attempts, kind.value, wait, exc,
            )
            if on_retry:
                try:
                    on_retry(attempt, kind, wait)
                except Exception:
                    pass
            time.sleep(wait)

    raise last_exc  # type: ignore[misc]


def strip_markdown_fences(text: str) -> str:
    """```json ... ``` 마크다운 펜스 제거."""
    text = re.sub(r"^```[a-z]*\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# P3-2: LLM 비용 추적
# ---------------------------------------------------------------------------

class LLMCostTracker:
    """누적 LLM 비용을 스레드-안전하게 추적한다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_usd: float = 0.0
        self._call_count: int = 0

    def record(self, litellm_response: Any) -> None:
        """litellm response 객체에서 비용을 추출해 누적한다."""
        try:
            import litellm as _ll
            cost = _ll.completion_cost(completion_response=litellm_response)
            with self._lock:
                self._total_usd += cost
                self._call_count += 1
        except Exception:
            pass

    @property
    def total_usd(self) -> float:
        with self._lock:
            return self._total_usd

    @property
    def call_count(self) -> int:
        with self._lock:
            return self._call_count

    def reset(self) -> None:
        with self._lock:
            self._total_usd = 0.0
            self._call_count = 0

    def snapshot(self) -> dict:
        with self._lock:
            return {"total_usd": round(self._total_usd, 6), "call_count": self._call_count}

    def check_budget(self, max_cost_usd: float | None) -> bool:
        """예산 초과 여부 반환 (True = 초과)."""
        if max_cost_usd is None or max_cost_usd <= 0:
            return False
        return self.total_usd >= max_cost_usd


# 모듈-레벨 싱글턴 (세션 단위로 리셋 가능)
_cost_tracker = LLMCostTracker()


def get_cost_tracker() -> LLMCostTracker:
    return _cost_tracker

"""Gemini client: structured JSON analysis with micro-batching and retries."""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import require_gemini_api_key
from app.gemini.prompt import SYSTEM_INSTRUCTION, build_batch_user_prompt
from app.gemini.rate_limit import RequestRateLimiter
from app.gemini.schema import GiveawayAnalysis, GiveawayBatchAnalysis, GiveawayBatchItemAnalysis

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 4
_BASE_DELAY_S = 1.0
_MAX_DELAY_S = 20.0
_QUOTA_FALLBACK_DELAY_S = 60.0
_QUOTA_SAFETY_MARGIN_S = 1.0

_RETRY_IN_RE = re.compile(
    r"(?:retry(?:\s+in)?|please retry in)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*"
    r"(s|sec|secs|second|seconds|m|min|mins|minute|minutes)?",
    re.IGNORECASE,
)
_RETRY_DELAY_FIELD_RE = re.compile(
    r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)(s|m)?",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class GeminiUsage:
    prompt_tokens: int | None = None
    candidates_tokens: int | None = None
    total_tokens: int | None = None

    def as_dict(self) -> dict[str, int]:
        out: dict[str, int] = {}
        if self.prompt_tokens is not None:
            out["prompt_tokens"] = self.prompt_tokens
        if self.candidates_tokens is not None:
            out["candidates_tokens"] = self.candidates_tokens
        if self.total_tokens is not None:
            out["total_tokens"] = self.total_tokens
        return out


@dataclass(slots=True, frozen=True)
class GeminiAnalysisResult:
    analysis: GiveawayAnalysis
    usage: GeminiUsage
    model: str
    raw_text: str


@dataclass(slots=True, frozen=True)
class GiveawayPageInput:
    giveaway_id: UUID
    url: str
    title: str | None
    text: str | None
    links: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class GeminiBatchResult:
    items: list[GiveawayBatchItemAnalysis]
    usage: GeminiUsage
    model: str
    raw_text: str


def _is_quota_error(exc: BaseException) -> bool:
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if code == 429:
            return True
        status = str(getattr(exc, "status", "") or "").upper()
        if status in {"RESOURCE_EXHAUSTED", "TOO_MANY_REQUESTS"}:
            return True
        message = str(exc).lower()
        return "resource_exhausted" in message or "quota" in message
    return False


def _is_retryable(exc: BaseException) -> bool:
    if _is_quota_error(exc):
        return True
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if code in {408, 500, 502, 503, 504}:
            return True
        message = str(exc).lower()
        return any(
            token in message
            for token in ("unavailable", "timeout", "temporarily", "rate")
        )
    return isinstance(exc, (TimeoutError, ConnectionError))


def _parse_retry_seconds_from_text(text: str) -> float | None:
    for pattern in (_RETRY_DELAY_FIELD_RE, _RETRY_IN_RE):
        match = pattern.search(text)
        if not match:
            continue
        value = float(match.group(1))
        unit = (match.group(2) or "s").lower()
        if unit.startswith("m"):
            return value * 60.0
        return value
    return None


def _walk_retry_delay(obj: Any) -> float | None:
    if obj is None:
        return None
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_l = str(key).lower()
            if key_l in {"retrydelay", "retry_delay"} and isinstance(value, (str, int, float)):
                parsed = _parse_retry_seconds_from_text(str(value))
                if parsed is not None:
                    return parsed
            if key_l in {"retryinfo", "retry_info"} or "retryinfo" in key_l.replace(".", ""):
                found = _walk_retry_delay(value)
                if found is not None:
                    return found
            found = _walk_retry_delay(value)
            if found is not None:
                return found
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found = _walk_retry_delay(item)
            if found is not None:
                return found
    elif isinstance(obj, str):
        return _parse_retry_seconds_from_text(obj)
    return None


def quota_retry_delay_seconds(exc: BaseException) -> float:
    """
    Honor server-provided retry delay for 429 / RESOURCE_EXHAUSTED.

    Adds a small safety margin. Falls back to 60s when the delay cannot be parsed.
    """
    delay: float | None = None
    if isinstance(exc, genai_errors.APIError):
        delay = _walk_retry_delay(getattr(exc, "details", None))
        if delay is None:
            delay = _parse_retry_seconds_from_text(str(exc))
    if delay is None:
        delay = _parse_retry_seconds_from_text(str(exc))
    if delay is None or delay <= 0:
        delay = _QUOTA_FALLBACK_DELAY_S
    return delay + _QUOTA_SAFETY_MARGIN_S


def _extract_usage(response: Any) -> GeminiUsage:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return GeminiUsage()
    return GeminiUsage(
        prompt_tokens=getattr(meta, "prompt_token_count", None),
        candidates_tokens=getattr(meta, "candidates_token_count", None),
        total_tokens=getattr(meta, "total_token_count", None),
    )


def _generate_content_config(*, response_schema: type[Any]) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=response_schema,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


class GeminiClient:
    """Wrapper around google-genai with Pydantic structured outputs + micro-batching."""

    def __init__(
        self,
        settings: Settings,
        *,
        rate_limiter: RequestRateLimiter | None = None,
    ) -> None:
        api_key = require_gemini_api_key(settings)
        self._model = settings.gemini_model
        if not self._model:
            raise ValueError("GEMINI_MODEL is required")
        self._client = genai.Client(api_key=api_key)
        self._rate_limiter = rate_limiter or RequestRateLimiter(
            settings.gemini_max_requests_per_minute
        )
        self._batch_size = settings.gemini_batch_size
        logger.debug(
            "Gemini client ready model=%s batch_size=%s rpm=%s",
            self._model,
            self._batch_size,
            self._rate_limiter.max_per_minute,
        )

    @property
    def model(self) -> str:
        return self._model

    @property
    def client(self) -> genai.Client:
        return self._client

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @property
    def rate_limiter(self) -> RequestRateLimiter:
        return self._rate_limiter

    def analyze_giveaway_page(
        self,
        *,
        url: str,
        title: str | None,
        text: str | None,
        links: list[str] | None = None,
        giveaway_id: UUID | None = None,
    ) -> GeminiAnalysisResult:
        """Single-page convenience wrapper around the micro-batch API."""
        gid = giveaway_id or UUID("00000000-0000-0000-0000-000000000001")
        batch = self.analyze_giveaway_batch(
            [
                GiveawayPageInput(
                    giveaway_id=gid,
                    url=url,
                    title=title,
                    text=text,
                    links=list(links or []),
                )
            ]
        )
        if not batch.items:
            raise ValueError("Gemini batch returned no items for single-page analysis")
        return GeminiAnalysisResult(
            analysis=batch.items[0].as_analysis(),
            usage=batch.usage,
            model=batch.model,
            raw_text=batch.raw_text,
        )

    def analyze_giveaway_batch(
        self,
        items: Sequence[GiveawayPageInput],
    ) -> GeminiBatchResult:
        """Analyze up to batch_size giveaways in ONE generate_content call."""
        if not items:
            raise ValueError("analyze_giveaway_batch requires at least one item")
        if len(items) > self._batch_size:
            raise ValueError(
                f"batch size {len(items)} exceeds GEMINI_BATCH_SIZE={self._batch_size}"
            )

        prompt_items = [
            (item.giveaway_id, item.url, item.title, item.text, list(item.links))
            for item in items
        ]
        prompt = build_batch_user_prompt(prompt_items)
        config = _generate_content_config(response_schema=GiveawayBatchAnalysis)

        last_exc: BaseException | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                self._rate_limiter.acquire()
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                )
                usage = _extract_usage(response)
                if usage.as_dict():
                    logger.info(
                        "gemini usage model=%s batch=%s %s",
                        self._model,
                        len(items),
                        " ".join(f"{k}={v}" for k, v in usage.as_dict().items()),
                    )

                parsed = getattr(response, "parsed", None)
                if isinstance(parsed, GiveawayBatchAnalysis):
                    batch = parsed
                    raw_text = response.text or ""
                else:
                    raw_text = response.text or ""
                    if not raw_text:
                        raise ValueError("Gemini returned empty response text")
                    batch = GiveawayBatchAnalysis.model_validate_json(raw_text)

                return GeminiBatchResult(
                    items=list(batch.items),
                    usage=usage,
                    model=self._model,
                    raw_text=raw_text,
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= _MAX_ATTEMPTS or not _is_retryable(exc):
                    logger.warning(
                        "gemini failed attempt=%s/%s retryable=%s error=%s",
                        attempt,
                        _MAX_ATTEMPTS,
                        _is_retryable(exc),
                        exc,
                    )
                    raise
                if _is_quota_error(exc):
                    delay = quota_retry_delay_seconds(exc)
                else:
                    delay = min(_MAX_DELAY_S, _BASE_DELAY_S * (2 ** (attempt - 1)))
                    delay *= 0.8 + random.random() * 0.4
                logger.warning(
                    "gemini retry attempt=%s/%s sleep=%.2fs quota=%s error=%s",
                    attempt,
                    _MAX_ATTEMPTS,
                    delay,
                    _is_quota_error(exc),
                    exc,
                )
                time.sleep(delay)

        assert last_exc is not None
        raise last_exc

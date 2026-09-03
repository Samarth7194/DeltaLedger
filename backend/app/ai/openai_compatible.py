from __future__ import annotations

import json
import random
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import anyio
import httpx
from pydantic import BaseModel, ValidationError

from app.ai.inference import InferenceMetadata, metadata_from_usage
from app.core.config import Settings
from app.core.exceptions import DeltaLedgerError

T = TypeVar("T", bound=BaseModel)

_RETRYABLE_STATUS_CODES = {408, 409, 425, 429}


class OpenAICompatibleClient:
    provider = "openai_compatible"

    # Shared across every instance in this process: all chat-completion call
    # sites (change/claim/contradiction classifiers) draw on the same Gemini
    # request-rate quota, so pacing must be tracked globally, not per client.
    _last_chat_call_monotonic: float | None = None

    def __init__(self, settings: Settings, *, provider_type: str) -> None:
        if not settings.ai_provider_api_key:
            raise DeltaLedgerError(
                "AI_PROVIDER_API_KEY is required for openai_compatible providers."
            )
        self.provider_type = provider_type
        self.base_url = settings.ai_provider_base_url.rstrip("/")
        self.timeout = settings.ai_provider_timeout_seconds
        self.max_retries = settings.ai_provider_max_retries
        self.retry_base_delay_seconds = settings.ai_provider_retry_base_delay_seconds
        self.retry_max_delay_seconds = settings.ai_provider_retry_max_delay_seconds
        self.retry_jitter_seconds = settings.ai_provider_retry_jitter_seconds
        self.chat_delay_seconds = settings.ai_provider_chat_delay_seconds
        self.input_cost_per_million = settings.ai_provider_input_token_cost_usd_per_million
        self.output_cost_per_million = settings.ai_provider_output_token_cost_usd_per_million
        self.headers = {
            "Authorization": f"Bearer {settings.ai_provider_api_key}",
            "Content-Type": "application/json",
        }

    async def embeddings(
        self,
        *,
        model: str,
        inputs: list[str],
        dimensions: int,
    ) -> tuple[list[list[float]], InferenceMetadata]:
        started = time.perf_counter()
        response, retry_count = await self._post(
            "/embeddings",
            {"model": model, "input": inputs, "dimensions": dimensions},
        )
        try:
            vectors = [
                [float(value) for value in item["embedding"]]
                for item in sorted(response["data"], key=lambda row: row.get("index", 0))
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise DeltaLedgerError("OpenAI-compatible embedding response was invalid.") from exc
        metadata = metadata_from_usage(
            provider=self.provider,
            provider_type=self.provider_type,
            model=model,
            model_version=(
                response.get("model") if isinstance(response.get("model"), str) else model
            ),
            prompt_version=None,
            latency_ms=(time.perf_counter() - started) * 1000,
            success=True,
            parse_status="valid",
            retry_count=retry_count,
            usage=response.get("usage") if isinstance(response.get("usage"), dict) else None,
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
        )
        return vectors, metadata

    async def chat_json(
        self,
        *,
        model: str,
        prompt_version: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_model: type[T],
    ) -> tuple[T, InferenceMetadata, dict[str, Any]]:
        await self._pace_chat_call()
        started = time.perf_counter()
        response, retry_count = await self._post(
            "/chat/completions",
            {
                "model": model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, sort_keys=True, default=str),
                    },
                ],
            },
        )
        raw_content = _message_content(response)
        try:
            parsed_payload = json.loads(raw_content)
            parsed = response_model.model_validate(parsed_payload)
            parse_status = "valid"
            error_type = None
        except (json.JSONDecodeError, ValidationError) as exc:
            metadata = metadata_from_usage(
                provider=self.provider,
                provider_type=self.provider_type,
                model=model,
                model_version=_response_model_name(response, model),
                prompt_version=prompt_version,
                latency_ms=(time.perf_counter() - started) * 1000,
                success=False,
                parse_status="invalid",
                retry_count=retry_count,
                usage=response.get("usage") if isinstance(response.get("usage"), dict) else None,
                input_cost_per_million=self.input_cost_per_million,
                output_cost_per_million=self.output_cost_per_million,
                error_type=exc.__class__.__name__,
            )
            raise StructuredOutputError(
                "Provider returned invalid structured output.",
                metadata,
            ) from exc
        metadata = metadata_from_usage(
            provider=self.provider,
            provider_type=self.provider_type,
            model=model,
            model_version=_response_model_name(response, model),
            prompt_version=prompt_version,
            latency_ms=(time.perf_counter() - started) * 1000,
            success=True,
            parse_status=parse_status,
            retry_count=retry_count,
            usage=response.get("usage") if isinstance(response.get("usage"), dict) else None,
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
            error_type=error_type,
        )
        return parsed, metadata, response

    async def _post(self, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        model = payload.get("model") if isinstance(payload.get("model"), str) else None
        status_code: int | None = None
        retry_after_seconds: float | None = None
        error_category = "unknown_error"
        error_message = "Unknown provider error"
        for attempt in range(self.max_retries):
            is_last_attempt = attempt == self.max_retries - 1
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}{path}",
                        headers=self.headers,
                        json=payload,
                    )
            except httpx.HTTPError as exc:
                status_code = None
                retry_after_seconds = None
                error_category = "network_error"
                error_message = f"{exc.__class__.__name__}: {exc}"
                if is_last_attempt:
                    break
                await anyio.sleep(self._retry_delay(attempt, None))
                continue

            if response.status_code in _RETRYABLE_STATUS_CODES or response.status_code >= 500:
                status_code = response.status_code
                retry_after_seconds = _parse_structured_retry_delay(
                    response
                ) or _parse_retry_after(response.headers.get("retry-after"))
                error_category = _error_category(status_code)
                error_message = _safe_error_message(response)
                if is_last_attempt:
                    break
                await anyio.sleep(self._retry_delay(attempt, retry_after_seconds))
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ProviderRequestError(
                    "OpenAI-compatible provider rejected the request with a "
                    f"non-retryable status {exc.response.status_code}: "
                    f"{_safe_error_message(response)}",
                    provider=self.provider,
                    provider_type=self.provider_type,
                    model=model,
                    status_code=exc.response.status_code,
                    retry_count=attempt,
                    retry_after_seconds=None,
                    error_category=_error_category(exc.response.status_code),
                ) from exc
            return response.json(), attempt

        raise ProviderRequestError(
            f"OpenAI-compatible provider request failed after {self.max_retries} "
            f"attempt(s): {error_message}",
            provider=self.provider,
            provider_type=self.provider_type,
            model=model,
            status_code=status_code,
            retry_count=self.max_retries,
            retry_after_seconds=retry_after_seconds,
            error_category=error_category,
        )

    async def _pace_chat_call(self) -> None:
        """Enforce a minimum gap since the last chat call, waiting only the
        remainder if one is still owed. A call with nothing queued after it
        (e.g. the last one in a loop) never sleeps on its own account.
        """
        if self.chat_delay_seconds <= 0:
            return
        last_call = OpenAICompatibleClient._last_chat_call_monotonic
        if last_call is not None:
            remaining = self.chat_delay_seconds - (time.monotonic() - last_call)
            if remaining > 0:
                await anyio.sleep(remaining)
        OpenAICompatibleClient._last_chat_call_monotonic = time.monotonic()

    def _retry_delay(self, attempt: int, retry_after_seconds: float | None) -> float:
        if retry_after_seconds is not None:
            return min(retry_after_seconds, self.retry_max_delay_seconds)
        backoff = self.retry_base_delay_seconds * (2**attempt)
        jitter = random.uniform(0, self.retry_jitter_seconds) if self.retry_jitter_seconds else 0.0
        return min(backoff + jitter, self.retry_max_delay_seconds)


class StructuredOutputError(DeltaLedgerError):
    def __init__(self, message: str, metadata: InferenceMetadata) -> None:
        super().__init__(message)
        self.metadata = metadata


class ProviderRequestError(DeltaLedgerError):
    """Raised when an OpenAI-compatible provider request ultimately fails.

    Carries enough detail for callers to log or report the failure usefully
    without ever including request headers (and therefore the API key).
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        provider_type: str,
        model: str | None,
        status_code: int | None,
        retry_count: int,
        retry_after_seconds: float | None,
        error_category: str,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.provider_type = provider_type
        self.model = model
        self.status_code = status_code
        self.retry_count = retry_count
        self.retry_after_seconds = retry_after_seconds
        self.error_category = error_category


def _error_category(status_code: int | None) -> str:
    if status_code is None:
        return "network_error"
    if status_code == 429:
        return "rate_limited"
    if status_code == 408:
        return "timeout"
    if status_code >= 500:
        return "server_error"
    if status_code >= 400:
        return "client_error"
    return "unknown_error"


def _safe_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message[:500]
        if isinstance(error, str):
            return error[:500]
    return json.dumps(payload)[:500]


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max((retry_at - datetime.now(UTC)).total_seconds(), 0.0)


_RETRY_MESSAGE_PATTERN = re.compile(r"retry in\s+([\d.]+)\s*s\b", re.IGNORECASE)
_MAX_RETRY_DELAY_SEARCH_DEPTH = 6


def _parse_structured_retry_delay(response: httpx.Response) -> float | None:
    """Prefer the provider's own retry hint over headers or exponential backoff.

    Google's Gemini API reports 429 quota resets via a ``google.rpc.RetryInfo``
    duration (``retryDelay``), but the exact JSON shape isn't guaranteed by the
    OpenAI-compatibility endpoint: it may or may not preserve a typed
    ``error.details`` array, the delay itself may be a duration string
    (``"34.7s"``), a bare number of seconds, or a protobuf
    ``{"seconds": .., "nanos": ..}`` object, and the key may be either
    ``retryDelay`` or ``retry_delay``. A depth-bounded recursive scan handles
    all of these without assuming one exact nesting. If no machine-readable
    value is found anywhere in the body, the human-readable message (which
    Gemini's free-tier 429s reliably include, e.g. "Please retry in
    34.725132932s") is used as a narrow, last-resort fallback.
    """
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        delay = _find_retry_delay(payload)
        if delay is not None:
            return delay
    return _parse_retry_delay_from_text(response.text)


def _find_retry_delay(node: object, *, _depth: int = 0) -> float | None:
    if _depth > _MAX_RETRY_DELAY_SEARCH_DEPTH:
        return None
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.replace("_", "").lower() == "retrydelay":
                parsed = _coerce_retry_delay_value(value)
                if parsed is not None:
                    return parsed
        for value in node.values():
            found = _find_retry_delay(value, _depth=_depth + 1)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_retry_delay(item, _depth=_depth + 1)
            if found is not None:
                return found
    return None


def _coerce_retry_delay_value(value: object) -> float | None:
    if isinstance(value, str):
        return _parse_duration_seconds(value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return max(float(value), 0.0)
    if isinstance(value, dict):
        try:
            seconds = float(value.get("seconds", 0) or 0)
            nanos = float(value.get("nanos", 0) or 0)
        except (TypeError, ValueError):
            return None
        return max(seconds + nanos / 1_000_000_000, 0.0)
    return None


def _parse_duration_seconds(value: str) -> float | None:
    value = value.strip()
    if value.endswith("s"):
        value = value[:-1]
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None


def _parse_retry_delay_from_text(text: str) -> float | None:
    if not text:
        return None
    match = _RETRY_MESSAGE_PATTERN.search(text)
    if not match:
        return None
    try:
        return max(float(match.group(1)), 0.0)
    except ValueError:
        return None


def _message_content(response: dict[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeltaLedgerError(
            "OpenAI-compatible chat response was missing message content."
        ) from exc
    if not isinstance(content, str):
        raise DeltaLedgerError("OpenAI-compatible chat response content was not a string.")
    return content


def _response_model_name(response: dict[str, Any], fallback: str) -> str:
    model = response.get("model")
    return model if isinstance(model, str) and model else fallback

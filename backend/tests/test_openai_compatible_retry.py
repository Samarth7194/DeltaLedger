from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from pydantic import BaseModel

from app.ai.openai_compatible import (
    OpenAICompatibleClient,
    ProviderRequestError,
    StructuredOutputError,
    _find_retry_delay,
    _parse_retry_after,
    _parse_structured_retry_delay,
)
from app.core.config import Settings

_NO_TEXT_GIVEN = object()


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, object] | None = None,
        *,
        headers: dict[str, str] | None = None,
        text: str | object = _NO_TEXT_GIVEN,
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        # Real httpx responses expose the same raw body via both .json() and
        # .text, so a fake built only from `payload` should too, unless a
        # caller deliberately wants to simulate non-JSON/malformed text.
        self.text = json.dumps(self._payload) if text is _NO_TEXT_GIVEN else text

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://provider.example/v1/embeddings")
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=request, response=self  # type: ignore[arg-type]
            )


class _FakeAsyncClient:
    responses: list[object] = []
    calls: list[dict[str, object]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
        self.calls.append({"url": url, "json": json})
        item = _FakeAsyncClient.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _settings(**overrides: object) -> Settings:
    return Settings(
        ai_provider_api_key="test-key",
        ai_provider_base_url="https://provider.example/v1",
        **overrides,
    )


async def _no_sleep(_seconds: float) -> None:
    return None


def _embedding_payload(values: list[float]) -> dict[str, object]:
    return {
        "model": "gemini-embedding-001",
        "data": [{"index": 0, "embedding": values}],
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }


class _EchoResult(BaseModel):
    value: str


class _TwoFieldResult(BaseModel):
    value: str
    reason: str


def _chat_response(value: str = "ok") -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "model": "test-chat-model",
        "choices": [{"message": {"content": json.dumps({"value": value})}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _raw_chat_response(content: str) -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "model": "test-chat-model",
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _quota_exceeded_payload(retry_delay: str = "15.693241900s") -> dict[str, object]:
    return {
        "error": {
            "code": 429,
            "message": "Quota exceeded for metric: generate_content_free_tier_requests.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure"},
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": retry_delay,
                },
            ],
        }
    }


def _real_apple_run_quota_payload() -> dict[str, object]:
    """The actual body shape observed against the real Gemini OpenAI-compatible
    endpoint during the Apple analysis run: no typed ``error.details`` array
    at all, just a free-text message carrying the retry hint."""
    return {
        "error": {
            "code": 429,
            "message": (
                "Quota exceeded for metric: "
                "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
                "limit: 5, model: gemini-3.6-flash. Please retry in 34.725132932s."
            ),
            "status": "RESOURCE_EXHAUSTED",
        }
    }


async def _chat_json(client: OpenAICompatibleClient) -> _EchoResult:
    result, _metadata, _raw = await client.chat_json(
        model="test-chat-model",
        prompt_version="test-v1",
        system_prompt="echo",
        user_payload={},
        response_model=_EchoResult,
    )
    return result


async def _chat_json_two_field(
    client: OpenAICompatibleClient,
) -> tuple[_TwoFieldResult, object]:
    result, metadata, _raw = await client.chat_json(
        model="test-chat-model",
        prompt_version="test-v1",
        system_prompt="classify",
        user_payload={},
        response_model=_TwoFieldResult,
    )
    return result, metadata


@pytest.mark.asyncio
async def test_post_honors_retry_after_header_in_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(429, headers={"retry-after": "3"}),
        _FakeResponse(200, _embedding_payload([1.0, 0.0])),
    ]
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _record_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)

    client = OpenAICompatibleClient(_settings(), provider_type="embedding")
    vectors, metadata = await client.embeddings(
        model="gemini-embedding-001", inputs=["a"], dimensions=2
    )

    assert vectors == [[1.0, 0.0]]
    assert sleep_calls == [3.0]
    assert metadata.retry_count == 1


@pytest.mark.asyncio
async def test_post_backs_off_exponentially_without_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(429),
        _FakeResponse(429),
        _FakeResponse(200, _embedding_payload([1.0])),
    ]
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _record_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr("app.ai.openai_compatible.random.uniform", lambda _a, _b: 0.0)

    client = OpenAICompatibleClient(
        _settings(
            ai_provider_max_retries=3,
            ai_provider_retry_base_delay_seconds=1.0,
            ai_provider_retry_max_delay_seconds=60.0,
        ),
        provider_type="embedding",
    )
    vectors, _metadata = await client.embeddings(model="m", inputs=["a"], dimensions=1)

    assert vectors == [[1.0]]
    assert sleep_calls == [1.0, 2.0]


@pytest.mark.asyncio
async def test_post_does_not_immediately_repeat_within_a_few_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAsyncClient.responses = [_FakeResponse(429), _FakeResponse(200, _embedding_payload([1.0]))]
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _record_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)

    client = OpenAICompatibleClient(
        _settings(ai_provider_retry_base_delay_seconds=1.0, ai_provider_retry_jitter_seconds=0.0),
        provider_type="embedding",
    )
    await client.embeddings(model="m", inputs=["a"], dimensions=1)

    assert sleep_calls[0] >= 1.0


@pytest.mark.asyncio
async def test_post_raises_provider_request_error_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAsyncClient.responses = [_FakeResponse(429, headers={"retry-after": "2"})] * 3
    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _no_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)

    client = OpenAICompatibleClient(
        _settings(ai_provider_max_retries=3), provider_type="embedding"
    )

    with pytest.raises(ProviderRequestError) as exc_info:
        await client.embeddings(model="gemini-embedding-001", inputs=["a"], dimensions=1)

    err = exc_info.value
    assert err.status_code == 429
    assert err.retry_count == 3
    assert err.error_category == "rate_limited"
    assert err.retry_after_seconds == 2.0
    assert err.provider == "openai_compatible"
    assert err.model == "gemini-embedding-001"
    assert "test-key" not in str(err)


@pytest.mark.asyncio
async def test_post_does_not_retry_non_retryable_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAsyncClient.responses = [_FakeResponse(401, {"error": {"message": "invalid api key"}})]
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _record_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)

    client = OpenAICompatibleClient(
        _settings(ai_provider_max_retries=5), provider_type="embedding"
    )

    with pytest.raises(ProviderRequestError) as exc_info:
        await client.embeddings(model="m", inputs=["a"], dimensions=1)

    assert sleep_calls == []
    assert exc_info.value.status_code == 401
    assert exc_info.value.retry_count == 0
    assert exc_info.value.error_category == "client_error"
    assert "invalid api key" in str(exc_info.value)


@pytest.mark.asyncio
async def test_post_retries_server_errors_and_eventually_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(503),
        _FakeResponse(200, _embedding_payload([1.0])),
    ]
    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _no_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)

    client = OpenAICompatibleClient(_settings(), provider_type="embedding")
    vectors, _metadata = await client.embeddings(model="m", inputs=["a"], dimensions=1)

    assert vectors == [[1.0]]


@pytest.mark.asyncio
async def test_post_retries_network_errors_and_eventually_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAsyncClient.responses = [
        httpx.ConnectError("boom"),
        _FakeResponse(200, _embedding_payload([1.0])),
    ]
    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _no_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)

    client = OpenAICompatibleClient(_settings(), provider_type="embedding")
    vectors, _metadata = await client.embeddings(model="m", inputs=["a"], dimensions=1)

    assert vectors == [[1.0]]


def test_parse_retry_after_accepts_seconds_and_http_dates() -> None:
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("5") == 5.0
    assert _parse_retry_after("not-a-value") is None

    future = datetime.now(UTC) + timedelta(seconds=10)
    parsed = _parse_retry_after(format_datetime(future))

    assert parsed is not None
    assert 0.0 <= parsed <= 11.0


def test_parse_structured_retry_delay_extracts_google_retry_info() -> None:
    response = _FakeResponse(429, _quota_exceeded_payload("15.693241900s"))

    assert _parse_structured_retry_delay(response) == pytest.approx(15.693241900)


def test_parse_structured_retry_delay_returns_none_without_retry_info() -> None:
    assert _parse_structured_retry_delay(_FakeResponse(429, {"error": {"message": "nope"}})) is None
    assert _parse_structured_retry_delay(_FakeResponse(429, {})) is None
    assert _parse_structured_retry_delay(_FakeResponse(429, text="not json")) is None


def test_parse_structured_retry_delay_falls_back_to_real_apple_run_message() -> None:
    """Reproduces the actual Apple-run failure: no error.details array at all,
    only a free-text message. This is the real shape the original details-only
    parser missed."""
    response = _FakeResponse(429, _real_apple_run_quota_payload())

    assert _parse_structured_retry_delay(response) == pytest.approx(34.725132932)


def test_find_retry_delay_supports_snake_case_key() -> None:
    payload = {"error": {"details": [{"retry_delay": "34.725132932s"}]}}

    assert _find_retry_delay(payload) == pytest.approx(34.725132932)


def test_find_retry_delay_supports_protobuf_duration_object() -> None:
    payload = {
        "error": {
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": {"seconds": 34, "nanos": 725132932},
                }
            ]
        }
    }

    assert _find_retry_delay(payload) == pytest.approx(34.725132932)


def test_find_retry_delay_supports_bare_numeric_seconds() -> None:
    payload = {"error": {"retryDelay": 34.7}}

    assert _find_retry_delay(payload) == pytest.approx(34.7)


def test_find_retry_delay_ignores_malformed_values_without_raising() -> None:
    assert _find_retry_delay({"error": {"retryDelay": None}}) is None
    assert _find_retry_delay({"error": {"retryDelay": {"seconds": "not-a-number"}}}) is None
    assert _find_retry_delay({"error": {"retryDelay": ["unexpected", "list"]}}) is None
    assert _find_retry_delay("not even a dict") is None


@pytest.mark.asyncio
async def test_post_uses_real_apple_run_retry_delay_instead_of_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves the ~34.7s Gemini quota delay is honored instead of the
    1s/2s/4s exponential backoff the base delay/multiplier would otherwise
    produce. Sleep is mocked so the test does not actually wait."""
    _FakeAsyncClient.responses = [
        _FakeResponse(429, _real_apple_run_quota_payload()),
        _FakeResponse(200, _chat_response()),
    ]
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _record_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(OpenAICompatibleClient, "_last_chat_call_monotonic", None)

    client = OpenAICompatibleClient(
        _settings(
            ai_provider_retry_base_delay_seconds=1.0,
            ai_provider_retry_max_delay_seconds=60.0,
        ),
        provider_type="disclosure_change_classifier",
    )
    result = await _chat_json(client)

    assert result.value == "ok"
    assert sleep_calls == [pytest.approx(34.725132932)]
    assert sleep_calls[0] not in (1.0, 2.0, 4.0)


@pytest.mark.asyncio
async def test_post_caps_a_very_long_structured_retry_delay_at_configured_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"error": {"message": "Please retry in 500.0s."}}
    _FakeAsyncClient.responses = [
        _FakeResponse(429, payload),
        _FakeResponse(200, _embedding_payload([1.0])),
    ]
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _record_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)

    client = OpenAICompatibleClient(
        _settings(ai_provider_retry_max_delay_seconds=60.0), provider_type="embedding"
    )
    await client.embeddings(model="m", inputs=["a"], dimensions=1)

    assert sleep_calls == [60.0]


@pytest.mark.asyncio
async def test_post_prefers_structured_retry_delay_over_header_and_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(
            429,
            _quota_exceeded_payload("15.69s"),
            headers={"retry-after": "999"},
        ),
        _FakeResponse(200, _chat_response()),
    ]
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _record_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(OpenAICompatibleClient, "_last_chat_call_monotonic", None)

    client = OpenAICompatibleClient(_settings(), provider_type="disclosure_change_classifier")
    result = await _chat_json(client)

    assert result.value == "ok"
    assert sleep_calls == [15.69]


@pytest.mark.asyncio
async def test_chat_json_paces_a_second_immediate_call_but_not_a_lone_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(200, _chat_response("first")),
        _FakeResponse(200, _chat_response("second")),
    ]
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _record_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(OpenAICompatibleClient, "_last_chat_call_monotonic", None)

    client = OpenAICompatibleClient(
        _settings(ai_provider_chat_delay_seconds=5.0),
        provider_type="disclosure_change_classifier",
    )

    first = await _chat_json(client)
    assert first.value == "first"
    assert sleep_calls == []

    second = await _chat_json(client)
    assert second.value == "second"
    assert len(sleep_calls) == 1
    assert 0.0 < sleep_calls[0] <= 5.0


@pytest.mark.asyncio
async def test_chat_json_does_not_pace_when_delay_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(200, _chat_response("first")),
        _FakeResponse(200, _chat_response("second")),
    ]
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _record_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(OpenAICompatibleClient, "_last_chat_call_monotonic", None)

    client = OpenAICompatibleClient(
        _settings(ai_provider_chat_delay_seconds=0.0),
        provider_type="disclosure_change_classifier",
    )

    await _chat_json(client)
    await _chat_json(client)

    assert sleep_calls == []


@pytest.mark.asyncio
async def test_chat_json_repairs_missing_required_field_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduces the real Apple-run failure: gemini-3.5-flash-lite returns
    otherwise-valid JSON that drops one required field (materiality_reason
    in production; `reason` here). A single repair round trip, carrying
    concise feedback about what was missing, should recover it without
    the caller ever seeing an error."""
    _FakeAsyncClient.responses = [
        _FakeResponse(200, _raw_chat_response(json.dumps({"value": "ok"}))),
        _FakeResponse(200, _raw_chat_response(json.dumps({"value": "ok", "reason": "fixed"}))),
    ]
    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _no_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(OpenAICompatibleClient, "_last_chat_call_monotonic", None)
    _FakeAsyncClient.calls = []

    client = OpenAICompatibleClient(_settings(), provider_type="disclosure_change_classifier")
    result, metadata = await _chat_json_two_field(client)

    assert result.value == "ok"
    assert result.reason == "fixed"
    assert metadata.success is True
    assert metadata.parse_status == "valid"
    # Exactly one repair round trip: the initial request plus one retry.
    assert len(_FakeAsyncClient.calls) == 2
    repair_messages = _FakeAsyncClient.calls[1]["json"]["messages"]
    assert repair_messages[0]["content"] == "classify"
    assert repair_messages[1]["role"] == "user"
    assert repair_messages[2] == {
        "role": "assistant",
        "content": json.dumps({"value": "ok"}),
    }
    assert repair_messages[3]["role"] == "user"
    assert "reason" in repair_messages[3]["content"]
    assert "Field required" in repair_messages[3]["content"]


@pytest.mark.asyncio
async def test_chat_json_raises_structured_output_error_when_repair_also_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The repair budget is bounded: if the corrected response is still
    invalid, this must fail cleanly with a useful message rather than
    retrying forever or silently fabricating the missing field."""
    _FakeAsyncClient.responses = [
        _FakeResponse(200, _raw_chat_response(json.dumps({"value": "ok"}))),
        _FakeResponse(200, _raw_chat_response(json.dumps({"value": "still missing"}))),
    ]
    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _no_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(OpenAICompatibleClient, "_last_chat_call_monotonic", None)
    _FakeAsyncClient.calls = []

    client = OpenAICompatibleClient(_settings(), provider_type="disclosure_change_classifier")

    with pytest.raises(StructuredOutputError) as exc_info:
        await _chat_json_two_field(client)

    # Bounded: exactly the initial attempt plus one repair attempt, no more.
    assert len(_FakeAsyncClient.calls) == 2
    assert "2 attempt(s)" in str(exc_info.value)
    assert "reason" in str(exc_info.value)
    assert "Field required" in str(exc_info.value)
    assert exc_info.value.metadata.success is False
    assert exc_info.value.metadata.parse_status == "invalid"


@pytest.mark.asyncio
async def test_chat_json_valid_first_response_never_triggers_a_repair_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(200, _raw_chat_response(json.dumps({"value": "ok", "reason": "fine"}))),
    ]
    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _no_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(OpenAICompatibleClient, "_last_chat_call_monotonic", None)
    _FakeAsyncClient.calls = []

    client = OpenAICompatibleClient(_settings(), provider_type="disclosure_change_classifier")
    result, metadata = await _chat_json_two_field(client)

    assert result.value == "ok"
    assert result.reason == "fine"
    assert len(_FakeAsyncClient.calls) == 1
    assert metadata.parse_status == "valid"


@pytest.mark.asyncio
async def test_chat_json_disabling_repair_restores_immediate_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AI_PROVIDER_STRUCTURED_OUTPUT_REPAIR_ATTEMPTS=0 must reproduce the
    original fail-immediately behavior exactly (no extra request)."""
    _FakeAsyncClient.responses = [
        _FakeResponse(200, _raw_chat_response(json.dumps({"value": "ok"}))),
    ]
    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _no_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(OpenAICompatibleClient, "_last_chat_call_monotonic", None)
    _FakeAsyncClient.calls = []

    client = OpenAICompatibleClient(
        _settings(ai_provider_structured_output_repair_attempts=0),
        provider_type="disclosure_change_classifier",
    )

    with pytest.raises(StructuredOutputError):
        await _chat_json_two_field(client)

    assert len(_FakeAsyncClient.calls) == 1


@pytest.mark.asyncio
async def test_chat_json_429_retry_behavior_is_unchanged_by_structured_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP-level 429/Retry-After handling inside _post() must keep working
    exactly as before, independent of the new structured-output repair
    loop -- a 429 followed by a valid response should not be mistaken for
    a structured-output repair round trip."""
    _FakeAsyncClient.responses = [
        _FakeResponse(429, headers={"retry-after": "3"}),
        _FakeResponse(200, _chat_response("ok")),
    ]
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.openai_compatible.anyio.sleep", _record_sleep)
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(OpenAICompatibleClient, "_last_chat_call_monotonic", None)
    _FakeAsyncClient.calls = []

    client = OpenAICompatibleClient(_settings(), provider_type="disclosure_change_classifier")
    result = await _chat_json(client)

    assert result.value == "ok"
    # The retry-after-driven sleep proves this was _post's own internal
    # 429 retry, not a structured-output repair round trip (which never
    # sleeps on a Retry-After header and only fires after a JSON/schema
    # validation failure, not a non-2xx status).
    assert sleep_calls == [3.0]
    assert len(_FakeAsyncClient.calls) == 2

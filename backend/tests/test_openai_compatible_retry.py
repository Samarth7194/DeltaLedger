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
    _parse_retry_after,
    _parse_structured_retry_delay,
)
from app.core.config import Settings


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, object] | None = None,
        *,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = text

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


def _chat_response(value: str = "ok") -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "model": "test-chat-model",
        "choices": [{"message": {"content": json.dumps({"value": value})}}],
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


async def _chat_json(client: OpenAICompatibleClient) -> _EchoResult:
    result, _metadata, _raw = await client.chat_json(
        model="test-chat-model",
        prompt_version="test-v1",
        system_prompt="echo",
        user_payload={},
        response_model=_EchoResult,
    )
    return result


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

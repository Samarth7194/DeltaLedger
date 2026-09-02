from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.ai.openai_compatible import (
    OpenAICompatibleClient,
    ProviderRequestError,
    _parse_retry_after,
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

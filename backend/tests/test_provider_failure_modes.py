"""The real OpenAI-compatible client + multi-item classifier against scripted
HTTP responses: partial/garbled/refused/rate-limited/timed-out responses, and
what each one leaves behind. No network."""

from __future__ import annotations

import json

import httpx
import pytest

from app.ai.inference import collect_usage
from app.ai.openai_compatible import (
    QUOTA_EXHAUSTED_DAILY,
    RATE_LIMITED_SHORT_TERM,
    RESOURCE_EXHAUSTED,
    ProviderRequestError,
)
from app.ai.semantic_change import ChangeClassificationRequest, OpenAICompatibleChangeClassifier
from app.core.config import Settings
from app.repositories.stage_batch_repository import is_retryable_error_type
from app.services.disclosure_change_service import DisclosureChangeService
from tests.test_disclosure_batch_classification import _passage, _section

_REAL_ASYNC_CLIENT = httpx.AsyncClient  # captured before any test patches it

VALID = {
    "change_type": "weakened",
    "summary": "s",
    "explanation": "e",
    "changed_spans": [],
    "confidence": 0.7,
    "risk_category": "liquidity",
    "materiality_reason": "m",
}


def _classifier(**overrides) -> OpenAICompatibleChangeClassifier:
    settings = Settings(
        _env_file=None,
        app_profile="local-cloud",
        environment="local",
        ai_provider_api_key="test-key",
        ai_provider_max_retries=3,
        ai_provider_retry_base_delay_seconds=0,
        ai_provider_retry_max_delay_seconds=0,
        ai_provider_retry_jitter_seconds=0,
        **overrides,
    )
    return OpenAICompatibleChangeClassifier(settings)


def _requests(count: int = 3) -> list[tuple[str, ChangeClassificationRequest]]:
    return [
        (
            f"i_{n}",
            ChangeClassificationRequest(
                previous_text=f"prev {n}",
                current_text=f"cur {n}",
                deterministic_signals={},
                section_metadata={},
                allowed_labels=["weakened"],
            ),
        )
        for n in range(count)
    ]


def _chat(content, *, usage=None, finish_reason="stop") -> httpx.Response:
    message = {"content": content}
    body = {
        "id": "resp-1",
        "model": "m",
        "choices": [{"message": message, "finish_reason": finish_reason}],
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def _items_json(*item_ids, drop=None, extra=()) -> str:
    entries = [
        {"item_id": item_id, **{**VALID, "summary": f"S:{item_id}"}}
        for item_id in item_ids
        if item_id != drop
    ]
    return json.dumps({"items": [*entries, *extra]})


def _script(monkeypatch, responses):
    """Serve `responses` in order (the last repeats). Returns the request log."""
    calls: list[httpx.Request] = []
    real_client = _REAL_ASYNC_CLIENT

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(
        "app.ai.openai_compatible.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    return calls


# --- partial / garbled provider output --------------------------------------------------


@pytest.mark.asyncio
async def test_valid_complete_and_reordered_responses_map_by_item_id(monkeypatch) -> None:
    _script(monkeypatch, [_chat(_items_json("i_2", "i_0", "i_1"))])

    outcomes = await _classifier().classify_batch(_requests(3))

    assert {k: v.summary for k, v in outcomes.items()} == {
        "i_0": "S:i_0",
        "i_1": "S:i_1",
        "i_2": "S:i_2",
    }


@pytest.mark.asyncio
async def test_missing_duplicate_unknown_and_malformed_items_are_isolated(monkeypatch) -> None:
    duplicated = [{"item_id": "i_1", **VALID}, {"item_id": "i_1", **VALID}]
    malformed = {"item_id": "i_3", "change_type": "not-a-label", "summary": "x"}
    payload = {
        "items": [
            {"item_id": "i_0", **{**VALID, "summary": "S:i_0"}},
            *duplicated,  # i_1 ambiguous
            # i_2 missing entirely
            malformed,  # i_3 schema-invalid
            {"item_id": "i_99", **VALID},  # unknown
        ]
    }
    _script(monkeypatch, [_chat(json.dumps(payload))])

    outcomes = await _classifier().classify_batch(_requests(4))

    assert outcomes["i_0"].summary == "S:i_0"  # the valid item is untouched
    assert outcomes["i_1"] is None and outcomes["i_2"] is None and outcomes["i_3"] is None
    assert "i_99" not in outcomes


@pytest.mark.asyncio
async def test_truncated_json_is_repaired_once_then_treated_as_unusable(monkeypatch) -> None:
    truncated = _items_json("i_0", "i_1")[:60]
    calls = _script(monkeypatch, [_chat(truncated, finish_reason="length")])

    outcomes = await _classifier().classify_batch(_requests(2))

    assert outcomes == {"i_0": None, "i_1": None}  # nothing attributable to any item
    assert len(calls) == 2  # the original request + exactly one repair attempt


@pytest.mark.asyncio
async def test_truncated_json_that_the_repair_attempt_fixes_is_used(monkeypatch) -> None:
    _script(
        monkeypatch,
        [_chat(_items_json("i_0", "i_1")[:60]), _chat(_items_json("i_0", "i_1"))],
    )

    outcomes = await _classifier().classify_batch(_requests(2))

    assert all(result is not None for result in outcomes.values())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _chat(None, finish_reason="content_filter"),  # refusal / safety block
        _chat(""),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"error": {"message": "refused"}}),
    ],
    ids=["null-content", "empty-content", "no-choices", "error-body-200"],
)
async def test_refusals_and_empty_completions_are_unusable_output_not_a_crash(
    monkeypatch, response
) -> None:
    _script(monkeypatch, [response])

    outcomes = await _classifier().classify_batch(_requests(2))

    assert outcomes == {"i_0": None, "i_1": None}


@pytest.mark.asyncio
async def test_unusable_output_never_becomes_a_silent_success(monkeypatch) -> None:
    """End to end through the service: a provider that only ever refuses leaves
    every item as an explicit, durable requires_review record - none of them is
    passed off as analysed."""
    _script(monkeypatch, [_chat(None, finish_reason="content_filter")])
    classifier = _classifier()
    service = DisclosureChangeService(
        Settings(_env_file=None, app_profile="local-cloud", environment="local"), classifier
    )
    from types import SimpleNamespace
    from uuid import uuid4

    candidates = [
        service.prepare_candidate(
            comparison_id=uuid4(),
            section_match=SimpleNamespace(id=uuid4()),
            passage_match=SimpleNamespace(id=uuid4()),
            previous_passage=_passage(f"We expect term{n}z demand to hold."),
            current_passage=_passage(f"We expect term{n}z demand may fall."),
            previous_section=_section(),
            current_section=_section(),
        )
        for n in range(3)
    ]

    outcome = await service.classify_candidates(candidates, known_results={})

    assert outcome.error is None
    assert {change.change_type for _, change in outcome.changes} == {"requires_review"}
    assert {record["status"] for record in outcome.records.values()} == {"requires_review"}
    assert len(outcome.records) == 3


# --- provider-level failures ---------------------------------------------------------------


def _error(status: int, body: dict | str, headers=None) -> httpx.Response:
    if isinstance(body, str):
        return httpx.Response(status, text=body, headers=headers)
    return httpx.Response(status, json=body, headers=headers)


@pytest.mark.asyncio
async def test_a_short_term_429_retries_with_backoff_then_reports_the_subtype(monkeypatch) -> None:
    body = {
        "error": {
            "message": "Quota exceeded for metric ... PerMinute ... Please retry in 21.5s",
            "details": [{"retryDelay": "21.5s"}],
        }
    }
    calls = _script(monkeypatch, [_error(429, body)])

    with pytest.raises(ProviderRequestError) as info:
        await _classifier().classify_batch(_requests(2))

    assert len(calls) == 3  # ai_provider_max_retries: bounded, never an infinite loop
    error = info.value
    assert error.error_category == "rate_limited"
    assert error.error_subtype == RATE_LIMITED_SHORT_TERM
    assert error.retry_after_seconds == 21.5
    assert error.is_retryable and is_retryable_error_type(error.error_subtype)


@pytest.mark.asyncio
async def test_daily_quota_exhaustion_fails_fast_instead_of_burning_retries(monkeypatch) -> None:
    body = {
        "error": {
            "message": "Quota exceeded for metric generate_content_free_tier_requests, "
            "quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 20"
        }
    }
    calls = _script(monkeypatch, [_error(429, body)])

    with pytest.raises(ProviderRequestError) as info:
        await _classifier().classify_batch(_requests(2))

    assert len(calls) == 1  # waiting cannot fix a daily quota
    assert info.value.error_subtype == QUOTA_EXHAUSTED_DAILY
    assert info.value.is_retryable  # retry later (after the quota resets), not never


@pytest.mark.asyncio
async def test_a_generic_resource_exhausted_429_is_classified_as_such(monkeypatch) -> None:
    calls = _script(monkeypatch, [_error(429, {"error": {"message": "RESOURCE_EXHAUSTED"}})])

    with pytest.raises(ProviderRequestError) as info:
        await _classifier().classify_batch(_requests(2))

    assert info.value.error_subtype == RESOURCE_EXHAUSTED
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_timeouts_and_network_errors_are_retryable_and_bounded(monkeypatch) -> None:
    calls = _script(monkeypatch, [httpx.ReadTimeout("slow")])

    with pytest.raises(ProviderRequestError) as info:
        await _classifier().classify_batch(_requests(2))
    assert (info.value.error_category, info.value.error_subtype) == ("timeout", "timeout")
    assert info.value.is_retryable and len(calls) == 3

    _script(monkeypatch, [httpx.ConnectError("down")])
    with pytest.raises(ProviderRequestError) as info:
        await _classifier().classify_batch(_requests(2))
    assert info.value.error_subtype == "network_error" and info.value.is_retryable


@pytest.mark.asyncio
async def test_a_rejected_request_is_not_retryable_and_not_retried(monkeypatch) -> None:
    calls = _script(monkeypatch, [_error(400, {"error": {"message": "bad request"}})])

    with pytest.raises(ProviderRequestError) as info:
        await _classifier().classify_batch(_requests(2))

    assert len(calls) == 1
    assert info.value.error_subtype == "provider_rejected"
    assert not info.value.is_retryable
    assert not is_retryable_error_type(info.value.error_subtype)


# --- usage ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_is_collected_across_the_repair_attempt(monkeypatch) -> None:
    usage_one = {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105}
    usage_two = {"prompt_tokens": 140, "completion_tokens": 60, "total_tokens": 200}
    _script(
        monkeypatch,
        [
            _chat(_items_json("i_0", "i_1")[:50], usage=usage_one),
            _chat(_items_json("i_0", "i_1"), usage=usage_two),
        ],
    )

    with collect_usage() as usage:
        await _classifier().classify_batch(_requests(2))

    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (240, 65, 305)
    assert usage.requests == 2 and usage.requests_reporting_usage == 2


@pytest.mark.asyncio
async def test_absent_usage_metadata_stays_none(monkeypatch) -> None:
    _script(monkeypatch, [_chat(_items_json("i_0", "i_1"))])  # no "usage" object

    with collect_usage() as usage:
        await _classifier().classify_batch(_requests(2))

    assert (usage.input_tokens, usage.output_tokens, usage.resolved_total()) == (None, None, None)
    assert usage.requests == 1 and usage.requests_reporting_usage == 0


@pytest.mark.asyncio
async def test_partially_reported_usage_is_not_padded_with_estimates(monkeypatch) -> None:
    _script(
        monkeypatch,
        [
            _chat(_items_json("i_0", "i_1")[:50], usage={"prompt_tokens": 90}),
            _chat(_items_json("i_0", "i_1")),  # this request reports nothing
        ],
    )

    with collect_usage() as usage:
        await _classifier().classify_batch(_requests(2))

    assert usage.input_tokens == 90 and usage.output_tokens is None
    assert usage.resolved_total() is None  # not derivable from what was reported

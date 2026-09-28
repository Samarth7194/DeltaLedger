from __future__ import annotations

import itertools
import uuid
from types import SimpleNamespace

import pytest

from app.ai.openai_compatible import ProviderRequestError, StructuredOutputError
from app.ai.semantic_change import (
    BatchClassificationResponse,
    ChangeClassificationRequest,
    ChangeClassificationResult,
    OpenAICompatibleChangeClassifier,
)
from app.core.config import Settings
from app.services.disclosure_change_service import (
    UNCLASSIFIABLE_CHANGE_TYPE,
    DisclosureChangeCallStats,
    DisclosureChangeService,
)

SECTION_ID = uuid.uuid4()
FILING_ID = uuid.uuid4()


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, app_profile="local-cloud", environment="local", **overrides)


def _result(label: str, *, confidence: float = 0.8) -> ChangeClassificationResult:
    return ChangeClassificationResult(
        change_type="weakened",
        summary=f"S:{label}",
        explanation="e",
        confidence=confidence,
        risk_category="liquidity",
        materiality_reason="m",
    )


def _valid_item(item_id: str, label: str) -> dict[str, object]:
    return {"item_id": item_id, **_result(label).model_dump(exclude={"inference_metadata"})}


def _section() -> SimpleNamespace:
    return SimpleNamespace(
        id=SECTION_ID,
        section_order=1,
        filing_id=FILING_ID,
        part_number="I",
        item_number="2",
        section_type="mda",
        canonical_section_type="mda",
        section_title="MD&A",
    )


_PASSAGE_COUNTER = itertools.count()


def _passage(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        unit_index=next(_PASSAGE_COUNTER),  # document position, like PassageUnit.unit_index
        text=text,
        source_anchor="a",
        raw_char_start=0,
        raw_char_end=len(text),
        content_hash="h",
    )


def make_candidates(service: DisclosureChangeService, count: int, *, stats=None):
    """`count` matched pairs that need the model (text really changed)."""
    candidates = []
    for index in range(count):
        word = f"word{index}x"
        candidates.append(
            service.prepare_candidate(
                comparison_id=uuid.uuid4(),
                section_match=SimpleNamespace(id=uuid.uuid4()),
                passage_match=SimpleNamespace(id=uuid.uuid4()),
                previous_passage=_passage(f"We expect {word} demand to remain resilient."),
                current_passage=_passage(f"We expect {word} demand may weaken materially."),
                previous_section=_section(),
                current_section=_section(),
                stats=stats,
            )
        )
    return candidates


class _ScriptedClassifier:
    """A multi-item capable classifier double. `bad_texts` are items the batch
    response cannot classify (returned as None); `hopeless_texts` also fail
    when retried alone."""

    model_name = "fake-model"
    model_version = "v1"
    prompt_version = "single-v1"
    batch_prompt_version = "batch-v1"
    batch_fixed_overhead_tokens = 0

    def __init__(
        self,
        *,
        bad_texts: tuple[str, ...] = (),
        hopeless_texts: tuple[str, ...] = (),
        provider_error_on_single: str | None = None,
        provider_error_on_batch: bool = False,
    ) -> None:
        self.bad_texts = bad_texts
        self.hopeless_texts = hopeless_texts
        self.provider_error_on_single = provider_error_on_single
        self.provider_error_on_batch = provider_error_on_batch
        self.batch_calls: list[list[str]] = []
        self.single_calls: list[str] = []

    async def classify_batch(self, items):
        self.batch_calls.append([item_id for item_id, _ in items])
        if self.provider_error_on_batch:
            raise _provider_error()
        return {
            item_id: (
                None
                if any(bad in (request.current_text or "") for bad in self.bad_texts)
                else _result(request.current_text or "")
            )
            for item_id, request in items
        }

    async def classify(self, request: ChangeClassificationRequest):
        text = request.current_text or ""
        self.single_calls.append(text)
        if self.provider_error_on_single and self.provider_error_on_single in text:
            raise _provider_error()
        if any(bad in text for bad in self.hopeless_texts):
            raise StructuredOutputError("invalid after repair", SimpleNamespace())
        return _result(text)


def _provider_error(
    subtype: str | None = None, retry_after: float | None = 15.0
) -> ProviderRequestError:
    return ProviderRequestError(
        "provider request failed after 5 attempt(s): quota exceeded",
        provider="openai_compatible",
        provider_type="disclosure_change_classifier",
        model="m",
        status_code=429,
        retry_count=5,
        retry_after_seconds=retry_after,
        error_category="rate_limited",
        error_subtype=subtype,
    )


@pytest.mark.asyncio
async def test_multi_item_batch_uses_one_request_and_maps_results_to_the_right_items() -> None:
    classifier = _ScriptedClassifier()
    service = DisclosureChangeService(_settings(), classifier)
    stats = DisclosureChangeCallStats()
    candidates = make_candidates(service, 5, stats=stats)

    outcome = await service.classify_candidates(candidates, known_results={}, stats=stats)

    assert outcome.error is None
    assert len(classifier.batch_calls) == 1 and classifier.single_calls == []
    assert (stats.gemini_calls, stats.batch_calls, stats.batched_items) == (1, 1, 5)
    assert len(outcome.changes) == 5
    for candidate, change in outcome.changes:
        # Each change carries the result for *its own* passage, tied to its
        # original evidence and passage match.
        assert change.change_summary == f"S:{candidate.current_text}"
        assert change.passage_match_id == candidate.passage_match.id
        assert change.supporting_evidence["current"]["passage_id"] == str(
            candidate.current_passage.id
        )
        assert change.detection_method == "hybrid"
        assert change.prompt_version == "batch-v1"


@pytest.mark.asyncio
async def test_one_bad_item_is_retried_alone_and_never_corrupts_the_others() -> None:
    classifier = _ScriptedClassifier(bad_texts=("word3x",))
    service = DisclosureChangeService(_settings(), classifier)
    stats = DisclosureChangeCallStats()
    candidates = make_candidates(service, 5, stats=stats)

    outcome = await service.classify_candidates(candidates, known_results={}, stats=stats)

    assert outcome.error is None
    assert len(classifier.batch_calls) == 1
    assert [text.split()[2] for text in classifier.single_calls] == ["word3x"]
    assert (stats.gemini_calls, stats.batched_items, stats.item_retries) == (2, 4, 1)
    by_candidate = {c.identity: change for c, change in outcome.changes}
    for candidate in candidates:
        change = by_candidate[candidate.identity]
        assert change.change_summary == f"S:{candidate.current_text}"
    retried = by_candidate[candidates[3].identity]
    assert retried.prompt_version == "single-v1"  # produced by the individual request
    assert by_candidate[candidates[0].identity].prompt_version == "batch-v1"


@pytest.mark.asyncio
async def test_an_item_unusable_even_alone_becomes_requires_review_only_for_itself() -> None:
    classifier = _ScriptedClassifier(bad_texts=("word1x",), hopeless_texts=("word1x",))
    service = DisclosureChangeService(_settings(), classifier)
    stats = DisclosureChangeCallStats()
    candidates = make_candidates(service, 3, stats=stats)

    outcome = await service.classify_candidates(candidates, known_results={}, stats=stats)

    assert outcome.error is None
    by_candidate = {c.identity: change for c, change in outcome.changes}
    failed = by_candidate[candidates[1].identity]
    assert failed.change_type == UNCLASSIFIABLE_CHANGE_TYPE
    assert failed.detection_method == "model_output_failed"
    assert failed.review_status == "uncertain"
    for good in (candidates[0], candidates[2]):
        assert by_candidate[good.identity].detection_method == "hybrid"
        assert by_candidate[good.identity].change_summary == f"S:{good.current_text}"
    assert stats.repair_fallbacks == 1


@pytest.mark.asyncio
async def test_provider_failure_keeps_items_that_already_succeeded() -> None:
    classifier = _ScriptedClassifier(
        bad_texts=("word0x", "word1x"), provider_error_on_single="word1x"
    )
    service = DisclosureChangeService(_settings(), classifier)
    candidates = make_candidates(service, 3)
    stats = DisclosureChangeCallStats()

    outcome = await service.classify_candidates(candidates, known_results={}, stats=stats)

    assert isinstance(outcome.error, ProviderRequestError)
    # word2x came back in the batch response, word0x was retried alone and
    # succeeded before word1x hit the quota failure: both are kept.
    kept = {c.current_text for c, _ in outcome.changes}
    assert kept == {candidates[0].current_text, candidates[2].current_text}


@pytest.mark.asyncio
async def test_a_batch_level_provider_failure_resolves_nothing_and_reports_the_error() -> None:
    classifier = _ScriptedClassifier(provider_error_on_batch=True)
    service = DisclosureChangeService(_settings(), classifier)
    candidates = make_candidates(service, 3)

    outcome = await service.classify_candidates(candidates, known_results={})

    assert isinstance(outcome.error, ProviderRequestError)
    assert outcome.changes == []
    assert classifier.single_calls == []  # no per-item fallback storm on a rate limit


@pytest.mark.asyncio
async def test_cached_items_are_not_sent_and_duplicate_text_pairs_are_sent_once() -> None:
    classifier = _ScriptedClassifier()
    service = DisclosureChangeService(_settings(), classifier)
    stats = DisclosureChangeCallStats()
    candidates = make_candidates(service, 3, stats=stats)
    duplicate = make_candidates(service, 1, stats=stats)[0]
    # Same text pair as candidates[0] (e.g. repeated boilerplate).
    duplicate.previous_text, duplicate.current_text = (
        candidates[0].previous_text,
        candidates[0].current_text,
    )
    duplicate.request = candidates[0].request
    known = {candidates[1].cache_key: _result(candidates[1].current_text or "")}

    outcome = await service.classify_candidates(
        [*candidates, duplicate], known_results=known, stats=stats
    )

    assert outcome.error is None
    sent = classifier.batch_calls[0]
    assert sorted(sent) == sorted([candidates[0].request_id, candidates[2].request_id])
    methods = {c.identity: change.detection_method for c, change in outcome.changes}
    assert methods[candidates[1].identity] == "hybrid_cached"
    assert methods[duplicate.identity] == "hybrid_cached"
    assert methods[candidates[0].identity] == "hybrid"
    assert stats.cache_reuses == 2


@pytest.mark.asyncio
async def test_frozen_failures_are_carried_over_without_asking_the_provider() -> None:
    classifier = _ScriptedClassifier()
    service = DisclosureChangeService(_settings(), classifier)
    candidates = make_candidates(service, 2)
    frozen = {candidates[0].cache_key: {"error": "StructuredOutputError", "message": "bad json"}}

    outcome = await service.classify_candidates(
        candidates, known_results={}, frozen_failures=frozen
    )

    # Only the non-frozen item is requested (alone, since it is the only one left).
    assert classifier.single_calls == [candidates[1].current_text]
    assert classifier.batch_calls == []
    by_candidate = {c.identity: change for c, change in outcome.changes}
    assert by_candidate[candidates[0].identity].change_type == UNCLASSIFIABLE_CHANGE_TYPE
    assert "bad json" in by_candidate[candidates[0].identity].change_explanation
    assert by_candidate[candidates[1].identity].detection_method == "hybrid"


@pytest.mark.asyncio
async def test_multi_item_requests_can_be_disabled_without_losing_batching() -> None:
    classifier = _ScriptedClassifier()
    service = DisclosureChangeService(_settings(ai_batch_multi_item_requests=False), classifier)
    candidates = make_candidates(service, 3)

    outcome = await service.classify_candidates(candidates, known_results={})

    assert classifier.batch_calls == []
    assert len(classifier.single_calls) == 3
    assert len(outcome.changes) == 3
    assert service.batch_prompt_version == "single-v1"


@pytest.mark.asyncio
async def test_unchanged_passages_are_resolved_locally_and_never_need_the_model() -> None:
    classifier = _ScriptedClassifier()
    service = DisclosureChangeService(_settings(), classifier)
    same = _passage("Cash and cash equivalents were sufficient.")
    stats = DisclosureChangeCallStats()
    candidate = service.prepare_candidate(
        comparison_id=uuid.uuid4(),
        section_match=SimpleNamespace(id=uuid.uuid4()),
        passage_match=SimpleNamespace(id=uuid.uuid4()),
        previous_passage=same,
        current_passage=_passage(same.text),
        previous_section=_section(),
        current_section=_section(),
        stats=stats,
    )

    outcome = await service.classify_candidates([candidate], known_results={}, stats=stats)

    assert candidate.needs_model is False
    assert outcome.changes[0][1].detection_method == "deterministic"
    assert classifier.batch_calls == [] and classifier.single_calls == []
    assert stats.deterministic_skips == 1


# --- the real provider-facing multi-item parsing --------------------------------------------


class _FakeChatClient:
    def __init__(self, response=None, *, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.payloads: list[dict] = []

    async def chat_json(self, **kwargs):
        self.payloads.append(kwargs["user_payload"])
        if self._error is not None:
            raise self._error
        return (
            BatchClassificationResponse(items=self._response),
            SimpleNamespace(model_dump=lambda: {"total_tokens": 1}),
            {"id": "resp-1"},
        )


def _real_classifier(client: _FakeChatClient) -> OpenAICompatibleChangeClassifier:
    classifier = OpenAICompatibleChangeClassifier(_settings(ai_provider_api_key="test-key"))
    classifier._client = client
    return classifier


def _requests(count: int) -> list[tuple[str, ChangeClassificationRequest]]:
    return [
        (
            f"i_{index}",
            ChangeClassificationRequest(
                previous_text=f"prev {index}",
                current_text=f"cur {index}",
                deterministic_signals={},
                section_metadata={},
                allowed_labels=["added", "removed"],
            ),
        )
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_batch_response_is_mapped_by_item_id_not_by_position() -> None:
    response = [_valid_item("i_2", "two"), _valid_item("i_0", "zero"), _valid_item("i_1", "one")]
    client = _FakeChatClient(response)

    outcomes = await _real_classifier(client).classify_batch(_requests(3))

    assert {item_id: result.summary for item_id, result in outcomes.items()} == {
        "i_0": "S:zero",
        "i_1": "S:one",
        "i_2": "S:two",
    }
    sent = client.payloads[0]
    assert [item["item_id"] for item in sent["items"]] == ["i_0", "i_1", "i_2"]
    assert "allowed_labels" not in sent["items"][0]  # hoisted once for the whole request
    assert sent["allowed_labels"] == ["added", "removed"]


@pytest.mark.asyncio
async def test_each_batch_item_is_validated_independently() -> None:
    invalid = _valid_item("i_3", "three")
    del invalid["materiality_reason"]  # the real observed failure: a dropped required field
    response = [
        _valid_item("i_0", "zero"),
        _valid_item("i_1", "one"),
        _valid_item("i_2", "two"),
        invalid,
        _valid_item("i_9", "unknown-id"),  # not requested -> ignored
    ]

    outcomes = await _real_classifier(_FakeChatClient(response)).classify_batch(_requests(4))

    assert outcomes["i_3"] is None
    assert [outcomes[key].summary for key in ("i_0", "i_1", "i_2")] == ["S:zero", "S:one", "S:two"]
    assert "i_9" not in outcomes


@pytest.mark.asyncio
async def test_missing_and_duplicated_item_ids_fall_back_to_individual_retry() -> None:
    response = [
        _valid_item("i_0", "zero"),
        _valid_item("i_1", "one-a"),
        _valid_item("i_1", "one-b"),  # ambiguous -> neither is trusted
    ]  # i_2 missing entirely

    outcomes = await _real_classifier(_FakeChatClient(response)).classify_batch(_requests(3))

    assert outcomes["i_0"].summary == "S:zero"
    assert outcomes["i_1"] is None
    assert outcomes["i_2"] is None


@pytest.mark.asyncio
async def test_unusable_envelope_marks_every_item_for_individual_retry() -> None:
    client = _FakeChatClient(error=StructuredOutputError("not json", SimpleNamespace()))

    outcomes = await _real_classifier(client).classify_batch(_requests(3))

    assert outcomes == {"i_0": None, "i_1": None, "i_2": None}


@pytest.mark.asyncio
async def test_provider_errors_are_not_swallowed_by_the_batch_call() -> None:
    client = _FakeChatClient(error=_provider_error())

    with pytest.raises(ProviderRequestError):
        await _real_classifier(client).classify_batch(_requests(2))

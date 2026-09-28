from __future__ import annotations

import pytest

from app.ai.inference import InferenceMetadata
from app.ai.openai_compatible import StructuredOutputError
from app.ai.semantic_change import ChangeClassificationResult, DeterministicFakeChangeClassifier
from app.core.config import Settings
from app.db.models import FilingSection, PassageMatch, PassageUnit, SectionMatch
from app.services.disclosure_change_service import (
    CACHED_DETECTION_METHOD,
    DETERMINISTIC_DETECTION_METHOD,
    MODEL_OUTPUT_FAILED_DETECTION_METHOD,
    UNCLASSIFIABLE_CHANGE_TYPE,
    DisclosureChangeCallStats,
    DisclosureChangeService,
)
from tests.integration_helpers import stable_uuid


def _settings(**overrides: object) -> Settings:
    # _env_file=None keeps this test isolated from whatever a developer's
    # local .env happens to be configured for (e.g. a real production-style
    # worker run), so it is deterministic regardless of machine state.
    return Settings(_env_file=None, app_profile="local-cloud", environment="local", **overrides)


def _section(key: str, *, text: str = "Liquidity remained sufficient.") -> FilingSection:
    return FilingSection(
        id=stable_uuid(key),
        filing_id=stable_uuid(f"{key}-filing"),
        section_type="mda",
        canonical_section_type="mda",
        part_number="I",
        item_number="2",
        section_title="Item 2. Management Discussion",
        section_order=0,
        raw_text=text,
        normalized_text=text.lower(),
        text_hash=key,
        token_count=len(text.split()),
        source_anchor=f"#{key}",
        metadata_={},
    )


def _passage(key: str, text: str) -> PassageUnit:
    return PassageUnit(
        id=stable_uuid(key),
        filing_section_id=stable_uuid(f"{key}-section"),
        unit_type="paragraph",
        unit_index=0,
        text=text,
        normalized_text=text.lower(),
        raw_char_start=0,
        raw_char_end=len(text),
        normalized_char_start=0,
        normalized_char_end=len(text),
        source_anchor=f"#{key}",
        content_hash=key,
        segmentation_version="test-v1",
        metadata_={},
    )


def _section_match(key: str, *, current_section_id, previous_section_id) -> SectionMatch:
    return SectionMatch(
        id=stable_uuid(key),
        comparison_id=stable_uuid("comparison"),
        current_section_id=current_section_id,
        previous_section_id=previous_section_id,
        match_type="exact_structural",
        combined_score=0.9,
        confidence=0.9,
        match_reason={},
    )


def _passage_match(key: str, *, section_match_id, current_passage_id, previous_passage_id):
    return PassageMatch(
        id=stable_uuid(key),
        section_match_id=section_match_id,
        current_passage_id=current_passage_id,
        previous_passage_id=previous_passage_id,
        alignment_type="matched",
        combined_score=0.7,
        confidence=0.7,
        alignment_metadata={},
    )


def _structured_output_error(
    message: str = "materiality_reason: Field required",
) -> StructuredOutputError:
    metadata = InferenceMetadata(
        provider="openai_compatible",
        provider_type="disclosure_change_classifier",
        model="gemini-3.5-flash-lite",
        success=False,
        parse_status="invalid",
        retry_count=1,
    )
    return StructuredOutputError(
        f"Provider returned invalid structured output after 2 attempt(s): {message}",
        metadata,
    )


class _AlwaysFailsClassifier:
    model_name = "gemini-3.5-flash-lite"
    model_version = "gemini-3.5-flash-lite"
    prompt_version = "disclosure-change-json-v1"

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    async def classify(self, request):
        self.calls += 1
        raise self._error


class _FailsOnceThenSucceedsClassifier:
    """Simulates a loop over several passages where exactly one item's
    repair attempts are exhausted and the rest classify normally."""

    model_name = "gemini-3.5-flash-lite"
    model_version = "gemini-3.5-flash-lite"
    prompt_version = "disclosure-change-json-v1"

    def __init__(self, *, fail_on_call: int, error: Exception) -> None:
        self._fail_on_call = fail_on_call
        self._error = error
        self._fallback = DeterministicFakeChangeClassifier()
        self.calls = 0

    async def classify(self, request):
        self.calls += 1
        if self.calls == self._fail_on_call:
            raise self._error
        return await self._fallback.classify(request)


class _CountingClassifier:
    """Delegates to DeterministicFakeChangeClassifier but counts calls, so
    tests can assert a Gemini call was (or wasn't) actually made."""

    model_name = "gemini-3.5-flash-lite"
    model_version = "gemini-3.5-flash-lite"
    prompt_version = "disclosure-change-json-v1"

    def __init__(self) -> None:
        self._delegate = DeterministicFakeChangeClassifier()
        self.calls = 0

    async def classify(self, request):
        self.calls += 1
        return await self._delegate.classify(request)


def _build_case(key: str, *, previous_text: str, current_text: str):
    previous_section = _section(f"{key}-prev-section", text=previous_text)
    current_section = _section(f"{key}-curr-section", text=current_text)
    previous = _passage(f"{key}-prev-passage", previous_text)
    current = _passage(f"{key}-curr-passage", current_text)
    section_match = _section_match(
        f"{key}-section-match",
        current_section_id=current_section.id,
        previous_section_id=previous_section.id,
    )
    passage_match = _passage_match(
        f"{key}-passage-match",
        section_match_id=section_match.id,
        current_passage_id=current.id,
        previous_passage_id=previous.id,
    )
    return {
        "section_match": section_match,
        "passage_match": passage_match,
        "current_passage": current,
        "previous_passage": previous,
        "current_section": current_section,
        "previous_section": previous_section,
    }


@pytest.mark.asyncio
async def test_valid_classification_is_unaffected_by_the_fallback_path() -> None:
    """A normal, successful classification (whether or not the provider
    needed an internal repair round trip - that machinery lives entirely
    inside chat_json() and is invisible here) must behave exactly as
    before: detect_change() never touches the fallback branch."""
    case = _build_case(
        "valid",
        previous_text="We will maintain sufficient liquidity.",
        current_text="We may need additional financing if demand declines.",
    )
    service = DisclosureChangeService(_settings(), DeterministicFakeChangeClassifier())

    change = await service.detect_change(comparison_id=stable_uuid("comparison"), **case)

    assert change is not None
    assert change.change_type != UNCLASSIFIABLE_CHANGE_TYPE
    assert change.detection_method == "hybrid"
    # Not explicitly set for a normal classification -- the DB column's
    # server_default="pending" applies on insert, not at construction time.
    assert change.review_status is None


@pytest.mark.asyncio
async def test_structured_output_repair_exhaustion_falls_back_instead_of_raising() -> None:
    case = _build_case(
        "exhausted",
        previous_text="We will maintain sufficient liquidity.",
        current_text="We may need additional financing if demand declines.",
    )
    error = _structured_output_error()
    classifier = _AlwaysFailsClassifier(error)
    service = DisclosureChangeService(_settings(), classifier)

    change = await service.detect_change(comparison_id=stable_uuid("comparison"), **case)

    # Did not raise, and did not silently drop the passage.
    assert change is not None
    assert classifier.calls == 1

    # Clearly marked as requiring analyst review / a model-output failure,
    # not a real classification.
    assert change.change_type == UNCLASSIFIABLE_CHANGE_TYPE
    assert change.detection_method == MODEL_OUTPUT_FAILED_DETECTION_METHOD
    assert change.review_status == "uncertain"
    assert change.confidence == 0.0

    # Evidence is preserved for analyst review even though classification
    # failed.
    assert change.supporting_evidence["current"]["passage_id"] == str(
        case["current_passage"].id
    )
    assert change.supporting_evidence["previous"]["passage_id"] == str(
        case["previous_passage"].id
    )

    # No fabricated materiality reasoning: the materiality breakdown is an
    # explicit failure marker, not synthesized novelty/risk/uncertainty
    # signals, and the recorded "model output" is the actual error, not an
    # invented ChangeClassificationResult.
    assert change.materiality_components == {
        "fallback": True,
        "reason": "structured_output_failed",
    }
    assert "materiality_reason" not in change.original_model_output
    assert change.original_model_output["error"] == "StructuredOutputError"
    assert "materiality_reason" in change.original_model_output["message"]
    assert "requires analyst review" in change.change_summary.lower()


@pytest.mark.asyncio
async def test_one_failed_classification_does_not_stop_the_remaining_passages() -> None:
    """Simulates FilingComparisonService's classification loop calling
    detect_change() once per passage match: the second call's repair
    exhaustion must not prevent the third call from running and succeeding."""
    error = _structured_output_error()
    classifier = _FailsOnceThenSucceedsClassifier(fail_on_call=2, error=error)
    service = DisclosureChangeService(_settings(), classifier)

    results = []
    for index in range(3):
        case = _build_case(
            f"loop-{index}",
            previous_text=f"Previous passage number {index}.",
            current_text=f"Current passage number {index}, changed.",
        )
        results.append(
            await service.detect_change(comparison_id=stable_uuid("comparison"), **case)
        )

    assert classifier.calls == 3
    assert all(result is not None for result in results)
    assert results[0].change_type != UNCLASSIFIABLE_CHANGE_TYPE
    assert results[1].change_type == UNCLASSIFIABLE_CHANGE_TYPE
    assert results[1].review_status == "uncertain"
    assert results[2].change_type != UNCLASSIFIABLE_CHANGE_TYPE


@pytest.mark.asyncio
async def test_identical_passage_text_skips_gemini_entirely() -> None:
    """Unchanged boilerplate (common across SEC filing quarters) needs no
    semantic judgment -- it must never reach the provider."""
    text = "We are subject to ordinary course legal proceedings."
    case = _build_case("identical", previous_text=text, current_text=text)
    classifier = _CountingClassifier()
    service = DisclosureChangeService(_settings(), classifier)
    stats = DisclosureChangeCallStats()

    change = await service.detect_change(
        comparison_id=stable_uuid("comparison"), stats=stats, **case
    )

    assert classifier.calls == 0
    assert change is not None
    assert change.change_type == "no_material_change"
    assert change.detection_method == DETERMINISTIC_DETECTION_METHOD
    assert change.confidence == 1.0
    assert change.original_model_output == {}
    assert stats.deterministic_skips == 1
    assert stats.gemini_calls == 0
    assert stats.candidate_pairs == 1


@pytest.mark.asyncio
async def test_near_identical_passage_text_skips_gemini_after_normalization() -> None:
    """Whitespace/case-only differences (e.g. a re-wrapped paragraph) are
    still deterministically "no material change", not a Gemini call."""
    case = _build_case(
        "near-identical",
        previous_text="We are subject to ordinary course legal proceedings.",
        current_text="  we are subject to ordinary  course legal proceedings.  ",
    )
    classifier = _CountingClassifier()
    service = DisclosureChangeService(_settings(), classifier)

    change = await service.detect_change(comparison_id=stable_uuid("comparison"), **case)

    assert classifier.calls == 0
    assert change is not None
    assert change.detection_method == DETERMINISTIC_DETECTION_METHOD
    assert "after normalization" in change.change_explanation


@pytest.mark.asyncio
async def test_repeated_boilerplate_across_passages_reuses_the_first_classification() -> None:
    """The same non-trivial text pair appearing more than once in a single
    comparison run (repeated boilerplate across sections) should only ever
    be classified by Gemini once; later occurrences reuse that result."""
    previous_text = "We will maintain sufficient liquidity."
    current_text = "We may need additional financing if demand declines."
    classifier = _CountingClassifier()
    service = DisclosureChangeService(_settings(), classifier)
    known_results: dict = {}
    stats = DisclosureChangeCallStats()

    first_case = _build_case("dup-a", previous_text=previous_text, current_text=current_text)
    second_case = _build_case("dup-b", previous_text=previous_text, current_text=current_text)

    first = await service.detect_change(
        comparison_id=stable_uuid("comparison"),
        known_results=known_results,
        stats=stats,
        **first_case,
    )
    second = await service.detect_change(
        comparison_id=stable_uuid("comparison"),
        known_results=known_results,
        stats=stats,
        **second_case,
    )

    assert classifier.calls == 1
    assert stats.gemini_calls == 1
    assert stats.cache_reuses == 1
    assert first.detection_method == "hybrid"
    assert second.detection_method == CACHED_DETECTION_METHOD
    # Same classification content, but each occurrence keeps its own
    # evidence/section/passage identity.
    assert second.change_type == first.change_type
    assert second.risk_category == first.risk_category
    assert second.section_match_id == second_case["section_match"].id
    assert second.passage_match_id == second_case["passage_match"].id
    assert second.supporting_evidence != first.supporting_evidence


@pytest.mark.asyncio
async def test_prior_persisted_result_is_reused_without_a_new_gemini_call() -> None:
    """Simulates a retry/resume: a classification already obtained (and
    persisted) in an earlier attempt is supplied as a seeded cache entry,
    and must be reused rather than re-classified."""
    previous_text = "We will maintain sufficient liquidity."
    current_text = "We may need additional financing if demand declines."
    classifier = _CountingClassifier()
    service = DisclosureChangeService(_settings(), classifier)

    # First "attempt": obtain and record a real classification result.
    first_case = _build_case("resume-a", previous_text=previous_text, current_text=current_text)
    first = await service.detect_change(comparison_id=stable_uuid("comparison"), **first_case)
    assert classifier.calls == 1

    # Second "attempt" (a resumed run): seed known_results the way
    # FilingComparisonService does from list_reusable_change_results(),
    # i.e. from the previously persisted original_model_output.
    seeded_cache = {
        (previous_text, current_text): ChangeClassificationResult.model_validate(
            first.original_model_output
        )
    }
    second_case = _build_case("resume-b", previous_text=previous_text, current_text=current_text)
    stats = DisclosureChangeCallStats()
    second = await service.detect_change(
        comparison_id=stable_uuid("comparison"),
        known_results=seeded_cache,
        stats=stats,
        **second_case,
    )

    assert classifier.calls == 1  # no new call on the "resumed" attempt
    assert stats.gemini_calls == 0
    assert stats.cache_reuses == 1
    assert second.detection_method == CACHED_DETECTION_METHOD
    assert second.change_type == first.change_type

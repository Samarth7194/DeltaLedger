"""BGE section matching / passage alignment is reused on resume when (and only
when) the filing pair, embedding model and matching config are unchanged."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.ai.openai_compatible import ProviderRequestError
from app.core.config import Settings
from app.services.comparison_fingerprint import matching_fingerprint
from tests.test_batch_hardening import SimulatedCrash, _CrashingAligner
from tests.test_comparison_batch_resume import _FailOnNthBatchClassifier, _Scenario
from tests.test_disclosure_batch_classification import _ScriptedClassifier


async def _first_run_fails_in_classification(scenario: _Scenario) -> None:
    with pytest.raises(ProviderRequestError):
        await scenario.run(_FailOnNthBatchClassifier(fail_on=2))
    assert scenario.matcher.calls == 1 and scenario.aligner.calls == 1
    assert scenario.comparison.processing_metrics.get("matching_fingerprint")


@pytest.mark.asyncio
async def test_a_downstream_ai_failure_does_not_invalidate_valid_matching() -> None:
    scenario = _Scenario(model_pairs=6, max_items=2)
    await _first_run_fails_in_classification(scenario)
    hashes = [row.input_hash for row in scenario.ledger()]

    classifier = _ScriptedClassifier()
    await scenario.run(classifier)  # a brand-new process resuming

    assert scenario.matcher.calls == 0 and scenario.aligner.calls == 0  # no BGE work at all
    metrics = scenario.comparison.processing_metrics
    assert metrics["matching_reused"] is True
    assert metrics["matching_seconds"] >= 0
    # The resumed run reached the first incomplete part directly: parts 1 (done)
    # were skipped and only the failed part and the rest were sent.
    assert metrics["classification_batches_skipped"] == 1
    assert len(classifier.batch_calls) == 2
    # Reused matches come back from the database in arbitrary order, yet the
    # batches are the same batches (same identity hashes), so resume lines up.
    assert [row.input_hash for row in scenario.ledger()] == hashes
    assert [row.status for row in scenario.ledger()] == ["completed"] * 3


@pytest.mark.asyncio
async def test_reuse_does_not_duplicate_section_or_passage_matches() -> None:
    scenario = _Scenario(model_pairs=6, max_items=2)
    await _first_run_fails_in_classification(scenario)
    before = (len(scenario.matches_db["section"]), len(scenario.matches_db["passage"]))
    passage_ids = {m.id for m in scenario.matches_db["passage"]}

    await scenario.run(_ScriptedClassifier())

    after_ids = [m.id for m in scenario.matches_db["passage"]]
    assert (len(scenario.matches_db["section"]), len(after_ids)) == before == (1, 6)
    assert set(after_ids) == passage_ids and len(after_ids) == len(set(after_ids))
    assert len(scenario.database) == 6  # one change per passage match


@pytest.mark.asyncio
async def test_recomputing_replaces_rather_than_appends_matches() -> None:
    scenario = _Scenario(model_pairs=4, max_items=2)
    await scenario.run(_ScriptedClassifier())
    scenario.embedding_version = "v2"
    scenario.comparison.status = "queued"

    await scenario.run(_ScriptedClassifier())

    assert scenario.matcher.calls == 1
    assert len(scenario.matches_db["passage"]) == 4  # not 8


@pytest.mark.asyncio
async def test_a_changed_embedding_model_invalidates_reuse() -> None:
    scenario = _Scenario(model_pairs=4, max_items=2)
    with pytest.raises(ProviderRequestError):
        await scenario.run(_FailOnNthBatchClassifier(fail_on=2))
    old_fingerprint = scenario.comparison.processing_metrics["matching_fingerprint"]

    scenario.embedding_version = "v2"  # e.g. a different BGE build
    await scenario.run(_ScriptedClassifier())

    assert scenario.matcher.calls == 1 and scenario.aligner.calls == 1  # recomputed
    metrics = scenario.comparison.processing_metrics
    assert metrics["matching_reused"] is False
    assert metrics["matching_fingerprint"] != old_fingerprint


@pytest.mark.asyncio
async def test_changed_matching_configuration_invalidates_reuse() -> None:
    scenario = _Scenario(model_pairs=4, max_items=2)
    with pytest.raises(ProviderRequestError):
        await scenario.run(_FailOnNthBatchClassifier(fail_on=2))

    scenario.settings_overrides = {"section_match_min_score": 0.91}
    await scenario.run(_ScriptedClassifier())

    assert scenario.matcher.calls == 1  # a threshold change can change the matches


@pytest.mark.asyncio
async def test_changed_filing_content_or_identity_invalidates_reuse() -> None:
    for mutate in (
        lambda s: setattr(s.current_section, "text_hash", "edited-current"),
        lambda s: setattr(s.previous_section, "text_hash", "edited-previous"),
        lambda s: setattr(s.comparison, "current_filing_id", uuid.uuid4()),
    ):
        scenario = _Scenario(model_pairs=4, max_items=2)
        with pytest.raises(ProviderRequestError):
            await scenario.run(_FailOnNthBatchClassifier(fail_on=2))
        mutate(scenario)
        if scenario.comparison.current_filing_id not in scenario.sections._sections_by_filing:
            # identity changed: point the (fake) section lookup at the new filing id
            scenario.sections._sections_by_filing[scenario.comparison.current_filing_id] = [
                scenario.current_section
            ]

        await scenario.run(_ScriptedClassifier())

        assert scenario.matcher.calls == 1, "stale matches were reused"


@pytest.mark.asyncio
async def test_an_interrupted_recompute_is_never_mistaken_for_complete_matching() -> None:
    scenario = _Scenario(model_pairs=4, max_items=2)
    await scenario.run(_ScriptedClassifier())
    assert scenario.comparison.processing_metrics["matching_fingerprint"]

    # A forced recompute dies while aligning (after wiping the old matches).
    scenario.embedding_version = "v2"
    scenario.comparison.status = "queued"
    with pytest.raises(SimulatedCrash):
        await scenario.run(_ScriptedClassifier(), aligner=_CrashingAligner({}))
    assert scenario.comparison.processing_metrics["matching_fingerprint"] is None

    await scenario.run(_ScriptedClassifier())  # same v2 config, but nothing valid to reuse

    assert scenario.matcher.calls == 1 and scenario.aligner.calls == 1
    assert len(scenario.matches_db["passage"]) == 4


@pytest.mark.asyncio
async def test_persisted_matches_that_disagree_with_their_recorded_counts_are_recomputed() -> None:
    scenario = _Scenario(model_pairs=4, max_items=2)
    with pytest.raises(ProviderRequestError):
        await scenario.run(_FailOnNthBatchClassifier(fail_on=2))
    scenario.matches_db["passage"].pop()  # a row went missing behind the marker's back

    await scenario.run(_ScriptedClassifier())

    assert scenario.matcher.calls == 1
    assert len(scenario.matches_db["passage"]) == 4


# --- the fingerprint itself ----------------------------------------------------------------


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, app_profile="local-cloud", environment="local", **overrides)


def _section(order, text_hash="h", chunks=()):
    return SimpleNamespace(
        id=uuid.UUID(int=order + 1), section_order=order, text_hash=text_hash, chunks=list(chunks)
    )


def _chunk(index, model="bge", content="c"):
    return SimpleNamespace(
        id=uuid.UUID(int=100 + index),
        chunk_index=index,
        content_hash=content,
        embedding_model=model,
        embedding_version="1",
    )


def _fp(settings=None, *, current=None, previous=None, model=("bge", "1"), comparison=None):
    return matching_fingerprint(
        settings=settings or _settings(),
        comparison=comparison
        or SimpleNamespace(
            comparison_version="v1", current_filing_id="a", comparison_filing_id="b"
        ),
        embedding_model_name=model[0],
        embedding_model_version=model[1],
        current_sections=current if current is not None else [_section(1), _section(2)],
        previous_sections=previous if previous is not None else [_section(1), _section(2)],
    )


def test_fingerprint_is_stable_and_independent_of_input_ordering() -> None:
    assert _fp() == _fp()
    assert _fp(current=[_section(2), _section(1)]) == _fp(current=[_section(1), _section(2)])
    # Speed-only settings never invalidate matching.
    assert _fp(_settings(embedding_batch_size=7, embedding_timeout_seconds=99)) == _fp()


def test_fingerprint_changes_with_every_input_that_affects_matching() -> None:
    base = _fp()
    changed = {
        "section text": _fp(current=[_section(1, "edited"), _section(2)]),
        "extra section": _fp(previous=[_section(1), _section(2), _section(3)]),
        "chunk content": _fp(current=[_section(1, chunks=[_chunk(0, content="new")]), _section(2)]),
        "chunk embedding model": _fp(
            current=[_section(1, chunks=[_chunk(0, model="other")]), _section(2)]
        ),
        "embedding model": _fp(model=("other-bge", "1")),
        "embedding version": _fp(model=("bge", "2")),
        "match threshold": _fp(_settings(section_match_min_score=0.91)),
        "alignment threshold": _fp(_settings(passage_alignment_min_score=0.91)),
        "reranker": _fp(_settings(reranker_enabled=True)),
        "comparison version": _fp(
            comparison=SimpleNamespace(
                comparison_version="v2", current_filing_id="a", comparison_filing_id="b"
            )
        ),
        "filing identity": _fp(
            comparison=SimpleNamespace(
                comparison_version="v1", current_filing_id="z", comparison_filing_id="b"
            )
        ),
    }
    for name, value in changed.items():
        assert value != base, f"{name} did not change the fingerprint"
    assert len(set(changed.values())) == len(changed)

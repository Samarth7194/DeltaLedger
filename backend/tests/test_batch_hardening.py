"""Hardening of durable batch resume: content-sensitive identity, real
crash/restart resume from a fresh process-equivalent, atomic completion,
provider usage and failure metadata."""

from __future__ import annotations

import uuid

import pytest

from app.ai.inference import record_usage
from app.ai.openai_compatible import ProviderRequestError
from app.repositories.stage_batch_repository import StageBatchRepository
from app.services.disclosure_change_service import DisclosureChangeService
from tests.batch_test_helpers import InMemoryBatchSession
from tests.test_comparison_batch_resume import (
    RUN_ID,
    _FailOnNthBatchClassifier,
    _Scenario,
)
from tests.test_disclosure_batch_classification import (
    _passage,
    _provider_error,
    _ScriptedClassifier,
    _section,
    _settings,
)
from tests.test_filing_comparison_service import _FakeAligner, _FakeSession


class SimulatedCrash(BaseException):
    """A process death / kill: not an Exception, so no handler in the service
    may catch it (nothing gets to record a failure)."""


class _CrashOnBatchClassifier(_ScriptedClassifier):
    def __init__(self, crash_on: int) -> None:
        super().__init__()
        self._crash_on = crash_on

    async def classify_batch(self, items):
        if len(self.batch_calls) + 1 == self._crash_on:
            self.batch_calls.append([item_id for item_id, _ in items])
            raise SimulatedCrash
        return await super().classify_batch(items)


class _CrashingAligner(_FakeAligner):
    """Dies during passage alignment - i.e. after the comparison re-run has
    already wiped the previous attempt's disclosure changes."""

    async def align_passages(self, **kwargs):
        raise SimulatedCrash


# ---------------------------------------------------------------------------------------
# 1. batch identity is content-sensitive
# ---------------------------------------------------------------------------------------


def _candidate(service, *, previous_id, current_id, previous_text, current_text):
    previous = _passage(previous_text)
    current = _passage(current_text)
    previous.id, current.id = previous_id, current_id
    return service.prepare_candidate(
        comparison_id=uuid.uuid4(),
        section_match=type("M", (), {"id": uuid.uuid4()})(),
        passage_match=type("M", (), {"id": uuid.uuid4()})(),
        previous_passage=previous,
        current_passage=current,
        previous_section=_section(),
        current_section=_section(),
    )


def test_item_identity_depends_on_content_not_just_ids() -> None:
    service = DisclosureChangeService(_settings(), _ScriptedClassifier())
    ids = {"previous_id": uuid.uuid4(), "current_id": uuid.uuid4()}
    text = {
        "previous_text": "We expect demand to hold.",
        "current_text": "We expect demand to soften.",
    }

    original = _candidate(service, **ids, **text)
    same_again = _candidate(service, **ids, **text)
    changed_current = _candidate(service, **ids, **{**text, "current_text": "Demand fell sharply."})
    changed_previous = _candidate(service, **ids, **{**text, "previous_text": "Demand was strong."})

    assert original.identity == same_again.identity
    assert original.content_hash == same_again.content_hash
    assert changed_current.identity != original.identity  # same ids, new text
    assert changed_previous.identity != original.identity
    assert original.identity.startswith(f"{ids['previous_id']}|{ids['current_id']}|")


@pytest.mark.asyncio
async def test_same_ids_with_changed_text_invalidate_a_completed_part() -> None:
    scenario = _Scenario(model_pairs=4, max_items=2)  # 2 parts
    await scenario.run(_ScriptedClassifier())
    assert [row.status for row in scenario.ledger()] == ["completed", "completed"]

    # Same passage ids, but the second part's passages now say something else
    # (e.g. re-ingest / re-segmentation): only that part's hash changes.
    for passages in scenario._passages.values():
        for passage in passages[2:]:
            passage.text = passage.text.replace("resilient", "fragile").replace(
                "weaken materially", "collapse entirely"
            )
    classifier = _ScriptedClassifier()
    await scenario.run(classifier)

    assert len(classifier.batch_calls) == 1  # part 1 reused, part 2 reclassified
    metrics = scenario.comparison.processing_metrics
    assert metrics["classification_batches_skipped"] == 1
    assert metrics["classification_batches_executed"] == 1
    summaries = {c.change_summary for c in scenario.database.values()}
    assert any("collapse entirely" in summary for summary in summaries)  # fresh, not stale


@pytest.mark.asyncio
async def test_same_content_resumes_a_completed_part_and_changed_context_does_not() -> None:
    scenario = _Scenario(model_pairs=4, max_items=2)
    await scenario.run(_ScriptedClassifier())

    again = _ScriptedClassifier()
    await scenario.run(again)
    assert again.batch_calls == [] and again.single_calls == []  # same content: reused

    hashes_before = [row.input_hash for row in scenario.ledger()]

    class _EditedPromptClassifier(_ScriptedClassifier):
        # Same version strings, but the prompt text itself was edited.
        prompt_fingerprint = "edited-prompt-text"

    await scenario.run(_EditedPromptClassifier())
    # The prompt fingerprint is part of the shared batch context, so the
    # batches are no longer the same batches.
    assert [row.input_hash for row in scenario.ledger()] != hashes_before


def test_real_classifiers_fold_the_prompt_text_hash_into_their_versions() -> None:
    from app.ai.financial_claims import OpenAICompatibleClaimExtractor
    from app.ai.semantic_change import OpenAICompatibleChangeClassifier

    for cls in (OpenAICompatibleChangeClassifier, OpenAICompatibleClaimExtractor):
        suffix = f"+{cls.prompt_fingerprint[:8]}"
        assert cls.prompt_version.endswith(suffix)
        assert cls.batch_prompt_version.endswith(suffix)
        assert len(cls.batch_prompt_version) <= 64  # fits the prompt_version column


@pytest.mark.asyncio
async def test_repository_resets_a_completed_batch_when_the_shared_context_changes() -> None:
    from app.ai.batching import BatchingConfig, BatchItem, plan_batches
    from app.db.models.workflow import BATCH_STAGE_FINANCIAL_CLAIMS as STAGE

    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    plan = plan_batches(
        [BatchItem("a", 5), BatchItem("b", 5)], BatchingConfig(2, 10_000, 0.0)
    )

    async def sync(context):
        return await repo.sync_plan(
            RUN_ID, STAGE, plan, model_name="m", prompt_version="p", context_hash=context
        )

    (state,) = await sync("metrics-v1")
    await repo.mark_completed(state.id)
    assert (await sync("metrics-v1"))[0].status == "completed"
    assert (await sync("metrics-v2"))[0].status == "pending"  # e.g. allowed_metrics changed


# ---------------------------------------------------------------------------------------
# 2. true crash / restart resume (everything rebuilt, nothing shared but the database)
# ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_killed_worker_resumes_at_the_processing_part_in_a_fresh_process() -> None:
    scenario = _Scenario(model_pairs=8, max_items=2)  # 4 parts

    with pytest.raises(SimulatedCrash):
        await scenario.run(_CrashOnBatchClassifier(crash_on=3))

    # Nothing had a chance to record anything on the way down.
    assert [row.status for row in scenario.ledger()] == [
        "completed",
        "completed",
        "processing",
        "pending",
    ]
    assert scenario.comparison.status not in {"completed", "failed"}

    # A completely new process: new session/repositories/service/classifier.
    fresh = _CrashOnBatchClassifier(crash_on=999)
    await scenario.run(fresh)

    assert len(fresh.batch_calls) == 2  # parts 3 and 4 only; 1 and 2 were skipped
    ledger = scenario.ledger()
    assert [row.status for row in ledger] == ["completed"] * 4
    assert [row.retry_count for row in ledger] == [0, 0, 1, 0]  # part 3 was re-attempted
    metrics = scenario.comparison.processing_metrics
    assert metrics["classification_batches_skipped"] == 2
    assert metrics["classification_batches_executed"] == 2
    assert len(scenario.database) == 8
    for change in scenario.database.values():
        assert change.change_summary == f"S:{change.current_text}"


@pytest.mark.asyncio
async def test_completed_parts_survive_a_crash_after_the_comparison_wiped_its_changes() -> None:
    """The window that matters most: a re-run wipes disclosure_changes, then
    dies (here: during alignment) before re-materialising anything. The ledger
    still says parts 1-2 are completed, so their results must come from the
    ledger itself - and must not be paid for with Gemini again."""
    scenario = _Scenario(model_pairs=8, max_items=2)
    with pytest.raises(SimulatedCrash):
        await scenario.run(_CrashOnBatchClassifier(crash_on=3))
    assert len(scenario.database) == 4  # parts 1-2 stored their changes

    # A re-run that must recompute matching (embedding model changed) wipes
    # disclosure_changes, then dies during alignment.
    scenario.embedding_version = "v2"
    crashing_aligner = _CrashingAligner({})
    with pytest.raises(SimulatedCrash):
        await scenario.run(_ScriptedClassifier(), aligner=crashing_aligner)
    assert scenario.database == {}  # wiped by the re-run; nothing re-materialised
    assert [row.status for row in scenario.ledger()][:2] == ["completed", "completed"]

    fresh = _ScriptedClassifier()
    await scenario.run(fresh)

    assert len(fresh.batch_calls) == 2  # parts 3-4 only: parts 1-2 cost nothing
    assert len(scenario.database) == 8  # ...and their results are back
    for passage_match in scenario.passage_matches:
        change = scenario.database[passage_match.id]
        assert change.change_summary == f"S:{change.current_text}"
    assert scenario.comparison.processing_metrics["classification_completed_batch_repairs"] == 0
    for row in scenario.ledger():
        assert len(row.item_results) == 2
        assert {r["status"] for r in row.item_results.values()} == {"success"}


@pytest.mark.asyncio
async def test_outputs_and_completion_commit_in_one_transaction_boundary(monkeypatch) -> None:
    events: list[str] = []
    original_commit = _FakeSession.commit

    async def logging_commit(self):
        events.append("commit")
        await original_commit(self)

    original_mark = StageBatchRepository.mark_completed

    async def logging_mark(self, *args, **kwargs):
        events.append("mark_completed")
        await original_mark(self, *args, **kwargs)

    from tests.test_comparison_batch_resume import _PersistingComparisonsRepo

    original_upsert = _PersistingComparisonsRepo.upsert_change_for_passage_match

    async def logging_upsert(self, passage_match_id, change):
        events.append("upsert")
        return await original_upsert(self, passage_match_id, change)

    monkeypatch.setattr(_FakeSession, "commit", logging_commit)
    monkeypatch.setattr(StageBatchRepository, "mark_completed", logging_mark)
    monkeypatch.setattr(
        _PersistingComparisonsRepo, "upsert_change_for_passage_match", logging_upsert
    )

    scenario = _Scenario(model_pairs=4, max_items=2)
    await scenario.run(_ScriptedClassifier())

    marks = [i for i, event in enumerate(events) if event == "mark_completed"]
    assert len(marks) == 2
    for index in marks:
        # Results were stored just before the mark, and the very next thing is
        # the commit: no commit can land between them, so a batch is never
        # committed as completed without its outputs (or vice versa).
        assert events[index - 1] == "upsert"
        assert events[index + 1] == "commit"


@pytest.mark.asyncio
async def test_items_resolved_before_a_failure_are_not_requested_again() -> None:
    scenario = _Scenario(model_pairs=2, max_items=2)  # one part, two items
    first = _ScriptedClassifier(bad_texts=("term1q",), provider_error_on_single="term1q")

    with pytest.raises(ProviderRequestError):
        await scenario.run(first)

    (row,) = scenario.ledger()
    assert row.status == "failed"
    assert (row.successful, len(row.item_results)) == (1, 1)  # item 0 kept durably

    retry = _ScriptedClassifier()
    await scenario.run(retry)

    assert retry.batch_calls == []
    assert len(retry.single_calls) == 1 and "term1q" in retry.single_calls[0]
    assert [r.status for r in scenario.ledger()] == ["completed"]
    assert len(scenario.database) == 2


# ---------------------------------------------------------------------------------------
# 5/6. usage and provider-failure metadata are persisted safely
# ---------------------------------------------------------------------------------------


class _UsageClassifier(_ScriptedClassifier):
    """Reports provider usage the way the real client does (per request)."""

    async def classify_batch(self, items):
        record_usage({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})
        return await super().classify_batch(items)

    async def classify(self, request):
        record_usage({"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50})
        return await super().classify(request)


@pytest.mark.asyncio
async def test_actual_usage_is_persisted_per_batch_and_summed_into_metrics() -> None:
    scenario = _Scenario(model_pairs=5, max_items=2)  # parts of 2, 2, 1 items

    await scenario.run(_UsageClassifier())

    ledger = scenario.ledger()
    assert [(r.actual_input, r.actual_output, r.actual_total) for r in ledger] == [
        (100, 20, 120),
        (100, 20, 120),
        (40, 10, 50),  # the 1-item part is a single request
    ]
    metrics = scenario.comparison.processing_metrics
    assert metrics["classification_actual_input_tokens"] == 240
    assert metrics["classification_actual_total_tokens"] == 290
    assert all(r.actual_input is not None for r in ledger)


@pytest.mark.asyncio
async def test_missing_usage_metadata_stays_null_never_estimated() -> None:
    scenario = _Scenario(model_pairs=4, max_items=2)

    await scenario.run(_ScriptedClassifier())  # reports no usage at all

    for row in scenario.ledger():
        assert (row.actual_input, row.actual_output, row.actual_total) == (None, None, None)
    metrics = scenario.comparison.processing_metrics
    assert metrics["classification_actual_input_tokens"] is None
    assert metrics["classification_actual_total_tokens"] is None


@pytest.mark.asyncio
async def test_usage_of_a_failed_attempt_is_kept_and_accumulates_over_retries() -> None:
    scenario = _Scenario(model_pairs=2, max_items=2)

    class _SpendsThenFails(_UsageClassifier):
        async def classify_batch(self, items):
            record_usage({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})
            raise _provider_error("rate_limited_short_term")

    with pytest.raises(ProviderRequestError):
        await scenario.run(_SpendsThenFails())
    (failed,) = scenario.ledger()
    assert failed.actual_total == 120  # spent tokens are real even though the request failed

    await scenario.run(_UsageClassifier())
    (done,) = scenario.ledger()
    assert (done.actual_input, done.actual_total) == (200, 240)  # both attempts counted
    assert done.retry_count == 1


@pytest.mark.asyncio
async def test_a_429_records_safe_metadata_and_leaves_completed_parts_untouched() -> None:
    scenario = _Scenario(model_pairs=6, max_items=2)

    class _RateLimited(_FailOnNthBatchClassifier):
        async def classify_batch(self, items):
            if len(self.batch_calls) + 1 == 3:
                self.batch_calls.append([i for i, _ in items])
                raise _provider_error("rate_limited_short_term", retry_after=21.5)
            return await _ScriptedClassifier.classify_batch(self, items)

    with pytest.raises(ProviderRequestError):
        await scenario.run(_RateLimited(fail_on=None))

    ledger = scenario.ledger()
    assert [r.status for r in ledger] == ["completed", "completed", "failed"]
    failed = ledger[2]
    assert failed.provider_error_type == "rate_limited_short_term"
    assert failed.retry_after == 21.5
    assert failed.provider_error_at is not None
    assert failed.error_category == "rate_limited"
    assert "Bearer" not in (failed.error_message or "")
    for done in ledger[:2]:  # untouched: still completed, still carrying results
        assert done.provider_error_type is None
        assert len(done.item_results) == 2
    assert scenario.comparison.status == "failed"  # retryable: the run can simply be re-run

    await scenario.run(_ScriptedClassifier())
    assert [r.status for r in scenario.ledger()] == ["completed"] * 3


def test_settings_still_validate_after_hardening() -> None:
    assert _settings().ai_batch_max_items >= 1

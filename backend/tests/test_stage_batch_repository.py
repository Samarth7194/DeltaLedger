from __future__ import annotations

import uuid

import pytest

from app.ai.batching import BatchingConfig, BatchItem, plan_batches
from app.db.models.workflow import BATCH_STAGE_DISCLOSURE_COMPARISON as STAGE
from app.repositories.stage_batch_repository import (
    StageBatchRepository,
    StageProgress,
    safe_error_message,
)
from app.services.analysis_progress import build_stage_progress
from tests.batch_test_helpers import InMemoryBatchSession, batch_rows

RUN_ID = uuid.uuid4()
CONFIG = BatchingConfig(max_items=2, input_token_budget=1_000_000, safety_margin=0.0)


def _plan(identities: list[str]):
    return plan_batches([BatchItem(identity, 10) for identity in identities], CONFIG)


async def _sync(repo, identities, *, model="m1", prompt="p1"):
    return await repo.sync_plan(
        RUN_ID, STAGE, _plan(identities), model_name=model, prompt_version=prompt
    )


@pytest.mark.asyncio
async def test_sync_plan_creates_pending_batches_with_stable_identity() -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)

    states = await _sync(repo, ["a", "b", "c", "d", "e"])

    assert [(s.batch_index, s.total_batches, s.status, s.item_count) for s in states] == [
        (1, 3, "pending", 2),
        (2, 3, "pending", 2),
        (3, 3, "pending", 1),
    ]
    rows = batch_rows(session.store, STAGE)
    assert rows[0].item_ids == ["a", "b"]
    assert len({row.input_hash for row in rows}) == 3


@pytest.mark.asyncio
async def test_sync_plan_is_idempotent_and_keeps_completed_batches() -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    first = await _sync(repo, ["a", "b", "c", "d"])
    await repo.mark_completed(first[0].id, provider_calls=1)
    hashes_before = [row.input_hash for row in batch_rows(session.store, STAGE)]

    second = await _sync(repo, ["a", "b", "c", "d"])

    assert [s.status for s in second] == ["completed", "pending"]
    assert [s.id for s in second] == [s.id for s in first]  # same rows, no duplicates
    assert len(session.store) == 2
    assert [row.input_hash for row in batch_rows(session.store, STAGE)] == hashes_before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "prompt"),
    [("m2", "p1"), ("m1", "p2")],
    ids=["model-version-change", "prompt-version-change"],
)
async def test_a_model_or_prompt_version_change_invalidates_completed_batches(
    model: str, prompt: str
) -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    first = await _sync(repo, ["a", "b", "c", "d"])
    for state in first:
        await repo.mark_completed(state.id, provider_calls=1)

    second = await _sync(repo, ["a", "b", "c", "d"], model=model, prompt=prompt)

    assert [s.status for s in second] == ["pending", "pending"]
    rows = batch_rows(session.store, STAGE)
    assert [row.provider_calls for row in rows] == [0, 0]
    assert len(session.store) == 2


@pytest.mark.asyncio
async def test_changed_items_reset_only_the_affected_batches() -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    first = await _sync(repo, ["a", "b", "c", "d"])
    for state in first:
        await repo.mark_completed(state.id)

    second = await _sync(repo, ["a", "b", "c", "X"])

    assert [s.status for s in second] == ["completed", "pending"]


@pytest.mark.asyncio
async def test_a_shorter_plan_removes_stale_batches() -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    await _sync(repo, ["a", "b", "c", "d", "e", "f"])
    assert len(session.store) == 3

    states = await _sync(repo, ["a", "b"])

    assert len(states) == 1
    assert [row.index for row in batch_rows(session.store, STAGE)] == [1]
    assert batch_rows(session.store, STAGE)[0].total == 1


@pytest.mark.asyncio
async def test_status_transitions_and_retry_counting() -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    (state,) = await _sync(repo, ["a"])

    await repo.mark_processing(state.id)
    assert batch_rows(session.store, STAGE)[0].retry_count == 0  # first attempt is not a retry

    await repo.mark_failed(
        state.id,
        error_category="rate_limited",
        error_message="quota exceeded",
        provider_calls=2,
    )
    failed = batch_rows(session.store, STAGE)[0]
    assert (failed.status, failed.error_category, failed.provider_calls) == (
        "failed",
        "rate_limited",
        2,
    )

    await repo.mark_processing(state.id)  # retry after a failure
    assert batch_rows(session.store, STAGE)[0].retry_count == 1

    await repo.mark_processing(state.id)  # retry after an interrupted (still processing) attempt
    assert batch_rows(session.store, STAGE)[0].retry_count == 2

    await repo.mark_completed(state.id, provider_calls=1)
    done = batch_rows(session.store, STAGE)[0]
    assert (done.status, done.provider_calls, done.error_category, done.error_message) == (
        "completed",
        3,
        None,
        None,
    )


def test_safe_error_message_is_bounded_and_scrubs_credentials() -> None:
    exc = RuntimeError(
        "request failed Authorization: Bearer sk-secret-value "
        "key=AIzaSyA1234567890abcdefghijklmnop api_key=hunter2 " + "x" * 2000
    )

    message = safe_error_message(exc)

    assert len(message) <= 500
    assert message.startswith("RuntimeError:")
    for leaked in ("sk-secret-value", "AIzaSyA1234567890", "hunter2"):
        assert leaked not in message


@pytest.mark.asyncio
async def test_stage_progress_reports_real_batch_counts() -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    states = await _sync(repo, list("abcdefghijkl"))  # 6 parts
    for state in states[:3]:
        await repo.mark_processing(state.id)
        await repo.mark_completed(state.id, provider_calls=1)
    await repo.mark_processing(states[3].id)
    await repo.mark_failed(
        states[3].id, error_category="rate_limited", error_message="quota", provider_calls=2
    )
    await repo.mark_processing(states[3].id)  # retried once
    await repo.mark_failed(
        states[3].id, error_category="rate_limited", error_message="quota"
    )

    progress = (await repo.stage_progress(RUN_ID))[STAGE]

    assert (progress.total, progress.completed, progress.failed, progress.pending) == (6, 3, 1, 2)
    assert (progress.provider_calls, progress.retries) == (5, 1)
    assert progress.status == "failed"
    assert progress.current_batch == 4  # the first incomplete part
    assert [part.status for part in progress.parts] == ["completed"] * 3 + ["failed"] + [
        "pending"
    ] * 2


def test_stage_progress_status_derivation() -> None:
    def make(**kw):
        base = {
            "stage": STAGE,
            "total": 4,
            "completed": 0,
            "processing": 0,
            "failed": 0,
            "pending": 4,
            "provider_calls": 0,
            "retries": 0,
        }
        return StageProgress(**{**base, **kw})

    assert make().status == "pending"
    assert make(completed=1, pending=3).status == "processing"
    assert make(completed=4, pending=0).status == "completed"
    assert make(completed=4, pending=0).current_batch is None
    assert make(completed=2, pending=2).current_batch == 3


def _progress(
    *,
    completed_nodes,
    current_node,
    run_status="processing_filings",
    failure_node=None,
    batches=None,
):
    return {
        entry["stage"]: entry
        for entry in build_stage_progress(
            completed_nodes=completed_nodes,
            current_node=current_node,
            run_status=run_status,
            failure_node=failure_node,
            batches=batches or {},
        )
    }


def test_api_progress_exposes_completed_and_total_parts() -> None:
    batches = {
        STAGE: StageProgress(STAGE, 14, 8, 1, 0, 5, 9, 0),
        "financial_claims": StageProgress("financial_claims", 5, 0, 0, 0, 5, 0, 0),
    }

    stages = _progress(
        completed_nodes=["validate_analysis_request"],
        current_node="run_disclosure_comparison",
        batches=batches,
    )

    disclosure = stages["disclosure_comparison"]
    assert (disclosure["status"], disclosure["completed_units"], disclosure["total_units"]) == (
        "processing",
        8,
        14,
    )
    assert disclosure["current_unit"] == 9
    assert disclosure["unit_label"] == "parts"
    assert disclosure["batched"] is True
    claims = stages["financial_claims"]
    assert (claims["status"], claims["completed_units"], claims["total_units"]) == (
        "pending",
        0,
        5,
    )
    # Not-batched stages carry status only - no invented unit counts.
    for name in ("xbrl_verification", "contradiction_analysis", "human_review", "final_report"):
        assert stages[name]["status"] == "pending"
        assert stages[name]["completed_units"] is None and stages[name]["total_units"] is None
        assert stages[name]["batched"] is False


def test_api_progress_marks_failed_and_completed_stages_from_real_state() -> None:
    stages = _progress(
        completed_nodes=["run_disclosure_comparison"],
        current_node=None,
        run_status="failed",
        failure_node="extract_financial_claims",
        batches={
            STAGE: StageProgress(STAGE, 14, 14, 0, 0, 0, 20, 0),
            "financial_claims": StageProgress("financial_claims", 5, 2, 0, 1, 2, 3, 1),
        },
    )

    assert stages["disclosure_comparison"]["status"] == "completed"
    assert stages["financial_claims"]["status"] == "failed"
    assert (
        stages["financial_claims"]["completed_units"],
        stages["financial_claims"]["total_units"],
    ) == (2, 5)
    assert stages["xbrl_verification"]["status"] == "pending"

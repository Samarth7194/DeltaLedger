"""StageBatchRepository.sync_plan must never let a completed batch be silently
reused when the plan it belongs to has changed in any way that could change
its meaning: reordered indices, a different total, different content at the
same index, a different model/prompt/context, or a different stage. Every
scenario here either keeps the batch valid (identical resubmission) or resets
it to pending with its results cleared - never a partial/stale reuse."""

from __future__ import annotations

import uuid

import pytest

from app.ai.batching import BatchingConfig, BatchItem, plan_batches
from app.db.models.workflow import BATCH_STAGE_DISCLOSURE_COMPARISON as DISCLOSURE
from app.db.models.workflow import BATCH_STAGE_FINANCIAL_CLAIMS as CLAIMS
from app.repositories.stage_batch_repository import StageBatchRepository
from tests.batch_test_helpers import InMemoryBatchSession, batch_rows

RUN_ID = uuid.uuid4()


def _plan(identities: list[str], *, max_items: int = 2):
    config = BatchingConfig(max_items=max_items, input_token_budget=1_000_000, safety_margin=0.0)
    return plan_batches([BatchItem(identity, 10) for identity in identities], config)


async def _sync(repo, identities, *, stage=DISCLOSURE, max_items=2, **kwargs):
    defaults = {"model_name": "m1", "prompt_version": "p1", "context_hash": "c1"}
    plan = _plan(identities, max_items=max_items)
    states = await repo.sync_plan(RUN_ID, stage, plan, **{**defaults, **kwargs})
    return states, plan


async def _complete_all(repo, states, plan):
    for state, planned in zip(states, plan, strict=True):
        await repo.mark_processing(state.id)
        results = {item_id: {"status": "success"} for item_id in planned.identities}
        await repo.mark_completed(state.id, item_results=results)


@pytest.mark.asyncio
async def test_item_order_change_at_the_same_index_invalidates_that_batch() -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    states, plan = await _sync(repo, ["a", "b", "c", "d"])
    await _complete_all(repo, states, plan)
    assert [row.status for row in batch_rows(session.store, DISCLOSURE)] == ["completed"] * 2

    # Same items, same batch boundaries, but b/a swapped within batch 1.
    reordered, _ = await _sync(repo, ["b", "a", "c", "d"])

    assert [state.status for state in reordered] == ["pending", "completed"]
    rows = batch_rows(session.store, DISCLOSURE)
    assert rows[0].item_ids == ["b", "a"]
    assert rows[0].item_results == {}  # cleared, not partially reused


@pytest.mark.asyncio
async def test_a_growing_total_batch_count_does_not_disturb_untouched_batches() -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    states, plan = await _sync(repo, ["a", "b"])
    await _complete_all(repo, states, plan)

    # More items appended: batch 1's content is unchanged, batch 2 is new.
    grown, _ = await _sync(repo, ["a", "b", "c", "d"])

    assert [state.status for state in grown] == ["completed", "pending"]
    rows = batch_rows(session.store, DISCLOSURE)
    assert [row.total for row in rows] == [2, 2]  # total_batches kept current on every row


@pytest.mark.asyncio
async def test_a_shrinking_total_batch_count_deletes_only_the_removed_indices() -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    states, plan = await _sync(repo, ["a", "b", "c", "d", "e", "f"])
    await _complete_all(repo, states, plan)
    assert len(session.store) == 3

    shrunk, _ = await _sync(repo, ["a", "b"])

    assert len(shrunk) == 1 and shrunk[0].status == "completed"
    assert len(session.store) == 1


@pytest.mark.asyncio
async def test_content_swapped_across_two_indices_invalidates_both_not_neither() -> None:
    """batch1=[a,b], batch2=[c,d] -> batch1=[c,d], batch2=[a,b]: the content
    that used to be "done" now lives at a different index. sync_plan must not
    mistake this for the original batch 1 or 2 still being valid at their old
    index - both must be treated as never having run, even though the same
    content was technically completed before."""
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    states, plan = await _sync(repo, ["a", "b", "c", "d"])
    await _complete_all(repo, states, plan)

    swapped, _ = await _sync(repo, ["c", "d", "a", "b"])

    assert [state.status for state in swapped] == ["pending", "pending"]
    rows = batch_rows(session.store, DISCLOSURE)
    assert rows[0].item_ids == ["c", "d"] and rows[1].item_ids == ["a", "b"]
    assert all(row.item_results == {} for row in rows)


@pytest.mark.asyncio
async def test_a_stage_name_mismatch_cannot_leak_batches_between_stages() -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    disclosure_states, disclosure_plan = await _sync(repo, ["a", "b"], stage=DISCLOSURE)
    await _complete_all(repo, disclosure_states, disclosure_plan)

    # Identical items/model/prompt/context, but a different stage: must be its
    # own, independent, pending plan - never treated as the disclosure batch.
    claim_states, _ = await _sync(repo, ["a", "b"], stage=CLAIMS)

    assert [state.status for state in claim_states] == ["pending"]
    assert [row.status for row in batch_rows(session.store, DISCLOSURE)] == ["completed"]
    assert [row.status for row in batch_rows(session.store, CLAIMS)] == ["pending"]


@pytest.mark.asyncio
async def test_resubmitting_the_identical_plan_is_a_true_no_op() -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    first, _ = await _sync(repo, ["a", "b", "c"])
    await repo.mark_processing(first[0].id)
    await repo.mark_completed(first[0].id, item_results={"a": {"status": "success"}})

    before = batch_rows(session.store, DISCLOSURE)
    again, _ = await _sync(repo, ["a", "b", "c"])
    after = batch_rows(session.store, DISCLOSURE)

    assert [state.id for state in again] == [state.id for state in first]
    assert before == after  # byte-for-byte unchanged: no spurious reset


@pytest.mark.asyncio
async def test_max_items_configuration_change_reshapes_batches_safely() -> None:
    """A config change (AI_BATCH_MAX_ITEMS) changes which items land in which
    batch even though the items themselves are unchanged; every affected
    batch must be invalidated, never silently kept under its old boundaries."""
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    states, plan = await _sync(repo, ["a", "b", "c", "d"], max_items=2)
    await _complete_all(repo, states, plan)

    reshaped, _ = await _sync(repo, ["a", "b", "c", "d"], max_items=4)

    assert len(reshaped) == 1
    assert reshaped[0].status == "pending"
    assert reshaped[0].item_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sync_override",
    [
        {"model_name": "m2"},
        {"prompt_version": "p2"},
        {"context_hash": "c2"},
    ],
    ids=["model", "prompt_version", "context"],
)
async def test_every_hash_input_independently_invalidates_completed_batches(
    sync_override: dict[str, str],
) -> None:
    session = InMemoryBatchSession()
    repo = StageBatchRepository(session)
    states, plan = await _sync(repo, ["a", "b", "c", "d"])
    await _complete_all(repo, states, plan)

    changed, _ = await _sync(repo, ["a", "b", "c", "d"], **sync_override)

    assert all(state.status == "pending" for state in changed)

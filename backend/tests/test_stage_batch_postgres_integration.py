"""Real-PostgreSQL coverage of the stage-batch ledger (needs
RUN_POSTGRES_TESTS=1 and a migrated test database, like the other Postgres
tests): the SQL the in-memory unit tests cannot exercise - constraints,
aggregation, cascade."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.ai.batching import BatchingConfig, BatchItem, plan_batches
from app.ai.inference import UsageTotals
from app.db.models import AnalysisRun, AnalysisStageBatch
from app.db.models.workflow import BATCH_STAGE_DISCLOSURE_COMPARISON, BATCH_STAGE_FINANCIAL_CLAIMS
from app.db.models.workflow import BATCH_STAGE_DISCLOSURE_COMPARISON as STAGE
from app.repositories.stage_batch_repository import ProviderErrorInfo, StageBatchRepository
from tests.integration_helpers import create_comparison_corpus

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

CONFIG = BatchingConfig(max_items=2, input_token_budget=1_000_000, safety_margin=0.0)


async def _run(session) -> AnalysisRun:
    corpus = await create_comparison_corpus(session)
    run = AnalysisRun(
        company_id=corpus["company_id"],
        current_filing_id=corpus["current_filing_id"],
        comparison_filing_id=corpus["comparison_filing_id"],
        workflow_version="test-v1",
        graph_version="test-v1",
        checkpoint_thread_id="thread-stage-batches",
    )
    session.add(run)
    await session.flush()
    return run


def _plan(identities):
    return plan_batches([BatchItem(identity, 10) for identity in identities], CONFIG)


@pytest.mark.asyncio
async def test_batch_ledger_round_trip_resume_and_progress(integration_session) -> None:
    run = await _run(integration_session)
    repo = StageBatchRepository(integration_session)

    first = await repo.sync_plan(
        run.id, STAGE, _plan(list("abcdef")), model_name="m", prompt_version="p1"
    )
    await repo.mark_processing(first[0].id)
    await repo.mark_completed(first[0].id, provider_calls=1)
    await repo.mark_processing(first[1].id)
    await repo.mark_failed(
        first[1].id, error_category="rate_limited", error_message="quota", provider_calls=1
    )
    await integration_session.commit()

    progress = (await repo.stage_progress(run.id))[STAGE]
    assert (progress.total, progress.completed, progress.failed, progress.pending) == (3, 1, 1, 1)
    assert progress.provider_calls == 2 and progress.current_batch == 2

    # Same plan again: nothing duplicated, statuses preserved (resume).
    resumed = await repo.sync_plan(
        run.id, STAGE, _plan(list("abcdef")), model_name="m", prompt_version="p1"
    )
    await integration_session.commit()
    assert [state.status for state in resumed] == ["completed", "failed", "pending"]
    assert len(await repo.list_batches(run.id, STAGE)) == 3

    # A prompt-version change invalidates everything.
    reset = await repo.sync_plan(
        run.id, STAGE, _plan(list("abcdef")), model_name="m", prompt_version="p2"
    )
    assert [state.status for state in reset] == ["pending"] * 3


@pytest.mark.asyncio
async def test_results_usage_and_error_metadata_round_trip_through_postgres(
    integration_session,
) -> None:
    run = await _run(integration_session)
    # Snapshot the scalar id now: `run` is an ORM object that `expire_all()`
    # below marks expired, and a later plain attribute access on it (e.g.
    # `run.id`) would trigger an implicit lazy refresh outside the async
    # greenlet context (MissingGreenlet). Every repository method already
    # takes a stable UUID, not the ORM object, so capturing it once up front
    # is all that's needed - the same pattern production code uses (see
    # AnalysisWorkflowService._invoke_graph's `run_id = run.id`).
    run_id = run.id
    repo = StageBatchRepository(integration_session)
    first, second = await repo.sync_plan(
        run_id, STAGE, _plan(list("abcd")), model_name="m", prompt_version="p", context_hash="c1"
    )
    await repo.mark_processing(first.id)
    await repo.mark_completed(
        first.id,
        provider_calls=1,
        item_results={
            "a": {"status": "success", "result": {"summary": "s"}},
            "b": {"status": "zero_result", "claims": 0},
        },
        usage=UsageTotals(
            requests=1,
            requests_reporting_usage=1,
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
        ),
    )
    await repo.mark_processing(second.id)
    await repo.mark_failed(
        second.id,
        error_category="rate_limited",
        error_message="quota",
        provider_error=ProviderErrorInfo("rate_limited_short_term", 21.5),
        item_results={"c": {"status": "requires_review", "error": "E", "message": "m"}},
    )
    await integration_session.commit()
    integration_session.expire_all()

    progress = (await repo.stage_progress(run_id))[STAGE]
    assert (progress.successful_items, progress.zero_result_items) == (1, 1)
    assert progress.requires_review_items == 1
    assert (progress.actual_input_tokens, progress.actual_total_tokens) == (100, 120)
    assert progress.actual_output_tokens == 20
    assert progress.last_provider_error_type == "rate_limited_short_term"
    assert progress.last_retry_after_seconds == 21.5
    assert progress.last_provider_error_at is not None
    # A part that never reported usage stays NULL rather than 0.
    assert progress.parts[1].actual_input_tokens is None
    stored = (await repo.list_batches(run_id, STAGE))[0]
    assert stored.item_results["a"]["result"] == {"summary": "s"}

    # Same plan + content + context resumes; a changed context resets the results.
    resumed = await repo.sync_plan(
        run_id, STAGE, _plan(list("abcd")), model_name="m", prompt_version="p", context_hash="c1"
    )
    assert [state.status for state in resumed] == ["completed", "failed"]
    assert set(resumed[0].item_results) == {"a", "b"}
    reset = await repo.sync_plan(
        run_id, STAGE, _plan(list("abcd")), model_name="m", prompt_version="p", context_hash="c2"
    )
    assert [state.status for state in reset] == ["pending", "pending"]
    assert reset[0].item_results == {}


@pytest.mark.asyncio
async def test_batch_index_is_unique_per_run_and_stage(integration_session) -> None:
    run = await _run(integration_session)
    row = dict(
        analysis_run_id=run.id,
        stage=STAGE,
        batch_index=1,
        total_batches=1,
        input_hash="h" * 64,
        item_count=1,
        estimated_input_tokens=1,
    )
    integration_session.add(AnalysisStageBatch(**row))
    await integration_session.flush()
    integration_session.add(AnalysisStageBatch(**row))

    with pytest.raises(IntegrityError):
        await integration_session.flush()
    await integration_session.rollback()


@pytest.mark.asyncio
async def test_batches_are_removed_with_their_analysis_run(integration_session) -> None:
    run = await _run(integration_session)
    await StageBatchRepository(integration_session).sync_plan(
        run.id, STAGE, _plan(["a", "b"]), model_name="m", prompt_version="p"
    )
    await integration_session.commit()

    await integration_session.execute(delete(AnalysisRun).where(AnalysisRun.id == run.id))
    await integration_session.commit()

    remaining = await integration_session.scalars(
        select(AnalysisStageBatch).where(AnalysisStageBatch.analysis_run_id == run.id)
    )
    assert remaining.all() == []


# --- real session-lifecycle hardening: every read below goes through a BRAND
# NEW engine + session + repository, never the one that wrote the data, so
# these prove durability against Postgres itself rather than against
# SQLAlchemy's in-process identity map. -----------------------------------------------------


@pytest.mark.asyncio
async def test_progress_survives_a_brand_new_session_after_commit_and_close(
    fresh_session_factory,
) -> None:
    async with fresh_session_factory() as session:
        run = await _run(session)
        run_id = run.id  # captured before the session that produced it is closed
        repo = StageBatchRepository(session)
        states = await repo.sync_plan(
            run_id, STAGE, _plan(list("abcdef")), model_name="m", prompt_version="p"
        )
        await repo.mark_processing(states[0].id)
        await repo.mark_completed(
            states[0].id,
            provider_calls=2,
            item_results={"a": {"status": "success"}, "b": {"status": "zero_result"}},
            usage=UsageTotals(
                requests=1,
                requests_reporting_usage=1,
                input_tokens=50,
                output_tokens=10,
                total_tokens=60,
            ),
        )
        await repo.mark_processing(states[1].id)
        await repo.mark_failed(
            states[1].id,
            error_category="rate_limited",
            error_message="quota",
            provider_error=ProviderErrorInfo("rate_limited_short_term", 12.0),
        )
        await repo.mark_processing(states[2].id)  # still "processing" when the process dies
        await session.commit()
        # The `async with` block exits here: engine disposed, connection gone -
        # simulating the worker process dying with nothing more written.

    # A completely new engine/session/repository: no shared identity map, no
    # shared connection, with the previous one already torn down.
    async with fresh_session_factory() as session:
        repo = StageBatchRepository(session)
        reloaded = {row.batch_index: row for row in await repo.list_batches(run_id, STAGE)}
        progress = (await repo.stage_progress(run_id))[STAGE]

    assert reloaded[1].status == "completed"
    assert reloaded[1].item_results == {"a": {"status": "success"}, "b": {"status": "zero_result"}}
    assert reloaded[1].provider_call_count == 2
    assert reloaded[2].status == "failed"
    assert reloaded[2].retry_count == 0  # the first attempt is not itself a retry
    assert reloaded[3].status == "processing"

    assert (progress.completed, progress.failed, progress.processing) == (1, 1, 1)
    assert (progress.actual_input_tokens, progress.actual_total_tokens) == (50, 60)
    failed_part = progress.parts[1]
    assert failed_part.last_provider_error_type == "rate_limited_short_term"
    assert failed_part.last_retry_after_seconds == 12.0


@pytest.mark.asyncio
async def test_a_processing_batch_is_resumable_from_a_new_session(fresh_session_factory) -> None:
    async with fresh_session_factory() as session:
        run = await _run(session)
        run_id = run.id
        (state,) = await StageBatchRepository(session).sync_plan(
            run_id, STAGE, _plan(["a", "b"]), model_name="m", prompt_version="p"
        )
        batch_id = state.id
        await StageBatchRepository(session).mark_processing(batch_id)
        await session.commit()  # died mid-batch: never marked completed or failed

    async with fresh_session_factory() as session:
        repo = StageBatchRepository(session)
        await repo.mark_processing(batch_id)  # the resumed attempt: counts as a retry
        await repo.mark_completed(batch_id, item_results={"a": {"status": "success"}})
        await session.commit()

    async with fresh_session_factory() as session:
        (row,) = await StageBatchRepository(session).list_batches(run_id, STAGE)
    assert (row.status, row.retry_count) == ("completed", 1)


@pytest.mark.asyncio
async def test_a_failed_retryable_batch_is_resumable_from_a_new_session(
    fresh_session_factory,
) -> None:
    async with fresh_session_factory() as session:
        run = await _run(session)
        run_id = run.id
        (state,) = await StageBatchRepository(session).sync_plan(
            run_id, STAGE, _plan(["a", "b"]), model_name="m", prompt_version="p"
        )
        batch_id = state.id
        await StageBatchRepository(session).mark_processing(batch_id)
        await StageBatchRepository(session).mark_failed(
            batch_id,
            error_category="rate_limited",
            error_message="quota exceeded",
            provider_error=ProviderErrorInfo("rate_limited_short_term", 5.0),
        )
        await session.commit()

    async with fresh_session_factory() as session:
        repo = StageBatchRepository(session)
        await repo.mark_processing(batch_id)
        await repo.mark_completed(batch_id, item_results={"a": {"status": "success"}})
        await session.commit()

    async with fresh_session_factory() as session:
        (row,) = await StageBatchRepository(session).list_batches(run_id, STAGE)
        progress = (await StageBatchRepository(session).stage_progress(run_id))[STAGE]
    assert (row.status, row.retry_count) == ("completed", 1)
    assert progress.failed == 0 and progress.completed == 1  # no lingering failure


@pytest.mark.asyncio
async def test_resuming_a_completed_batch_does_not_duplicate_it_or_its_output(
    fresh_session_factory,
) -> None:
    async with fresh_session_factory() as session:
        run = await _run(session)
        run_id = run.id
        repo = StageBatchRepository(session)
        (state,) = await repo.sync_plan(
            run_id, STAGE, _plan(["a", "b"]), model_name="m", prompt_version="p"
        )
        await repo.mark_processing(state.id)
        await repo.mark_completed(state.id, item_results={"a": {"status": "success"}})
        await session.commit()

    # A new "worker" resyncs the identical plan, as a real resume attempt would.
    async with fresh_session_factory() as session:
        repo = StageBatchRepository(session)
        resynced = await repo.sync_plan(
            run_id, STAGE, _plan(["a", "b"]), model_name="m", prompt_version="p"
        )
        await session.commit()
    assert len(resynced) == 1 and resynced[0].id == state.id  # same row, not a duplicate

    async with fresh_session_factory() as session:
        rows = await StageBatchRepository(session).list_batches(run_id, STAGE)
    assert len(rows) == 1
    assert rows[0].item_results == {"a": {"status": "success"}}  # untouched, not re-run


@pytest.mark.asyncio
async def test_deleting_the_run_cascades_stage_batches_seen_from_a_new_session(
    fresh_session_factory,
) -> None:
    async with fresh_session_factory() as session:
        run = await _run(session)
        run_id = run.id
        await StageBatchRepository(session).sync_plan(
            run_id, STAGE, _plan(["a", "b", "c", "d"]), model_name="m", prompt_version="p"
        )
        await session.commit()

    async with fresh_session_factory() as session:
        assert len(await StageBatchRepository(session).list_batches(run_id, STAGE)) == 2
        await session.execute(delete(AnalysisRun).where(AnalysisRun.id == run_id))
        await session.commit()

    async with fresh_session_factory() as session:
        remaining = await session.scalars(
            select(AnalysisStageBatch).where(AnalysisStageBatch.analysis_run_id == run_id)
        )
    assert remaining.all() == []


# --- Task 3: full multi-part resume simulation across new sessions, for both
# batched stages. No provider is called - the point is durable Postgres state. -------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", [BATCH_STAGE_DISCLOSURE_COMPARISON, BATCH_STAGE_FINANCIAL_CLAIMS])
async def test_a_worker_death_mid_batch_resumes_correctly_in_a_brand_new_process(
    fresh_session_factory, stage
) -> None:
    plan = _plan(list("abcdefgh"))  # 4 batches of 2 items each
    assert len(plan) == 4

    # --- "worker process #1": plans, completes parts 1-2, starts part 3, dies ---
    async with fresh_session_factory() as session:
        run = await _run(session)
        run_id = run.id
        repo = StageBatchRepository(session)
        states = await repo.sync_plan(run_id, stage, plan, model_name="m", prompt_version="p")
        for index, state in enumerate(states[:2]):
            await repo.mark_processing(state.id)
            await repo.mark_completed(
                state.id,
                provider_calls=1,
                item_results={item: {"status": "success"} for item in plan[index].identities},
            )
        await repo.mark_processing(states[2].id)  # part 3: started, never finished
        await session.commit()
        # process dies here: session/engine torn down, nothing more written.

    # --- "worker process #2": brand-new engine/session, resumes from scratch ---
    processed_parts: list[int] = []
    async with fresh_session_factory() as session:
        repo = StageBatchRepository(session)
        resumed = await repo.sync_plan(run_id, stage, plan, model_name="m", prompt_version="p")
        assert [s.status for s in resumed] == ["completed", "completed", "processing", "pending"]

        for position, state in enumerate(resumed):
            if state.status == "completed":
                continue  # part 1 and 2: skipped, never re-sent to a provider
            processed_parts.append(position + 1)
            await repo.mark_processing(state.id)  # part 3: resumed; part 4: started fresh
            await repo.mark_completed(
                state.id,
                provider_calls=1,
                item_results={item: {"status": "success"} for item in plan[position].identities},
            )
        await session.commit()

    assert processed_parts == [3, 4]

    # --- verified from a THIRD brand-new session: everything landed durably ---
    async with fresh_session_factory() as session:
        final = await StageBatchRepository(session).list_batches(run_id, stage)

    assert len(final) == 4  # no duplicate rows from the resume
    assert [row.status for row in final] == ["completed"] * 4
    assert [row.retry_count for row in final] == [0, 0, 1, 0]  # only part 3 was ever retried
    assert all(row.item_results for row in final)  # every part's output is present
    assert final[2].provider_call_count == 1  # part 3 wasn't billed twice for its old attempt

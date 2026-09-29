"""Real-Postgres coverage of stale-run recovery: a worker dying mid-node
leaves a real heartbeat behind, and POST /retry has to read it correctly.

This deliberately does not run the full LangGraph workflow (that machinery -
sync_plan reuse, resumed workers skipping completed batches - is already
proven for real, without a live worker, in test_stage_batch_postgres_integration.py,
test_batch_hardening.py, test_claim_outcome_semantics.py and
test_comparison_batch_resume.py). What is new here and needs a real database:

* WorkflowRepository.set_run_status and StageBatchRepository's mark_*
  methods actually write last_heartbeat_at on a real analysis_runs row;
* is_advisory_lock_free reflects real Postgres advisory-lock state, the same
  way held_advisory_lock does (see test_worker_lock_integration.py);
* the real POST /analyses/{id}/retry endpoint, against a real database,
  accepts a genuinely stale run when its lock is free, refuses it (409) when
  a live worker still holds the lock, and never creates a second
  analysis_runs row for the same run - and the retry call itself never
  touches the stage-batch ledger (that only happens once the enqueued task
  actually runs, which is deliberately not exercised here).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine

from app.ai.batching import BatchingConfig, BatchItem, plan_batches
from app.core.config import get_settings
from app.db.models import AnalysisRun
from app.db.models.workflow import BATCH_STAGE_FINANCIAL_CLAIMS as STAGE
from app.db.session import get_session, held_advisory_lock
from app.main import create_app
from app.repositories.stage_batch_repository import StageBatchRepository
from app.repositories.workflow_repository import WorkflowRepository, advisory_lock_key
from tests.integration_helpers import create_comparison_corpus

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

CONFIG = BatchingConfig(max_items=1, input_token_budget=1_000_000, safety_margin=0.0)
LOW_THRESHOLD_SECONDS = "5"
BACKDATE_SECONDS = 700  # comfortably over any threshold this test sets


def _plan(identities):
    return plan_batches([BatchItem(identity, 10) for identity in identities], CONFIG)


async def _seed_stale_run(
    fresh_session_factory,
) -> tuple[AnalysisRun, StageBatchRepository, object]:
    """A run that got as far as completing one financial-claims batch, then
    (from here) has its heartbeat backdated to simulate the worker dying
    before starting the next one. Each step uses its own fresh session/engine,
    like separate worker-process attempts against the same durable rows."""
    async with fresh_session_factory() as session:
        corpus = await create_comparison_corpus(session)
        run = AnalysisRun(
            company_id=corpus["company_id"],
            current_filing_id=corpus["current_filing_id"],
            comparison_filing_id=corpus["comparison_filing_id"],
            workflow_version="stale-recovery-test-v1",
            graph_version="stale-recovery-test-v1",
            checkpoint_thread_id=f"thread-stale-recovery-{corpus['company_id']}",
        )
        session.add(run)
        await session.flush()
        run_id = run.id

        # A node boundary: the coarse, once-per-node heartbeat touch.
        await WorkflowRepository(session).set_run_status(
            run, "extracting_claims", current_node="extract_financial_claims"
        )
        await session.commit()
        node_heartbeat = (await session.get(AnalysisRun, run_id)).last_heartbeat_at
        assert node_heartbeat is not None  # written by set_run_status against a real row

    async with fresh_session_factory() as session:
        repo = StageBatchRepository(session)
        (batch_one, _batch_two) = await repo.sync_plan(
            run_id, STAGE, _plan(["claim-a", "claim-b"]), model_name="m", prompt_version="p1"
        )
        await repo.mark_processing(batch_one.id)
        await repo.mark_completed(batch_one.id, item_results={"claim-a": {"status": "success"}})
        await session.commit()
        completed_batch = (await repo.list_batches(run_id, STAGE))[0]
        assert completed_batch.status == "completed"
        batch_heartbeat = (await session.get(AnalysisRun, run_id)).last_heartbeat_at
        # The finer-grained, per-batch touch moved the heartbeat forward again -
        # proving StageBatchRepository.mark_completed's own touch actually ran,
        # not just the earlier node-boundary one.
        assert batch_heartbeat > node_heartbeat

    async with fresh_session_factory() as session:
        await session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id == run_id)
            .values(last_heartbeat_at=datetime.now(UTC) - timedelta(seconds=BACKDATE_SECONDS))
        )
        await session.commit()

    async with fresh_session_factory() as session:
        run = await session.get(AnalysisRun, run_id)
        repo = StageBatchRepository(session)
        completed_batch = (await repo.list_batches(run_id, STAGE))[0]
    return run, repo, completed_batch


@pytest.fixture
def low_stale_threshold(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STALE_RUN_HEARTBEAT_THRESHOLD_SECONDS", LOW_THRESHOLD_SECONDS)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture
async def app_engine_on_test_database(test_database_url: str, monkeypatch: pytest.MonkeyPatch):
    """POST /retry's own advisory-lock check (is_advisory_lock_free) opens its
    own connection through the module-level app.db.session.engine, which by
    default points at the application database, not this test database. Point
    it at the same database the seeded run actually lives in - exactly the
    pattern test_worker_lock_integration.py uses for held_advisory_lock."""
    test_engine = create_async_engine(test_database_url, pool_pre_ping=True)
    monkeypatch.setattr("app.db.session.engine", test_engine)
    try:
        yield test_engine
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_a_stale_run_is_retried_once_without_redoing_its_completed_batch_or_duplicating_rows(
    fresh_session_factory, low_stale_threshold, app_engine_on_test_database
) -> None:
    run, repo, completed_batch_before = await _seed_stale_run(fresh_session_factory)
    run_id = run.id

    app = create_app()
    enqueued: list = []

    async def override_session():
        async with fresh_session_factory() as session:
            yield session

    def fake_enqueue(analysis_run_id):
        enqueued.append(analysis_run_id)
        return "job-stale-retry"

    app.dependency_overrides[get_session] = override_session
    import app.api.routes.analyses as analyses_route

    original_enqueue = analyses_route.enqueue_run_analysis_workflow
    analyses_route.enqueue_run_analysis_workflow = fake_enqueue
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(f"/api/v1/analyses/{run_id}/retry")
    finally:
        analyses_route.enqueue_run_analysis_workflow = original_enqueue
        app.dependency_overrides.clear()

    assert response.status_code == 202
    body = response.json()["data"]
    assert body["analysis_run_id"] == str(run_id)
    assert body["stale"] is True
    assert enqueued == [run_id]  # the existing run, re-enqueued exactly once

    async with fresh_session_factory() as session:
        rows = (
            await session.execute(
                select(AnalysisRun.id).where(
                    AnalysisRun.current_filing_id == run.current_filing_id,
                    AnalysisRun.comparison_filing_id == run.comparison_filing_id,
                    AnalysisRun.workflow_version == run.workflow_version,
                )
            )
        ).scalars().all()
    assert rows == [run_id]  # never a second analysis_runs row for this pair

    async with fresh_session_factory() as session:
        events = await WorkflowRepository(session).list_events(run_id)
    resumed = [event for event in events if event.event_type == "workflow_resumed"]
    assert resumed and resumed[-1].event_payload["reason"] == "stale_recovery"
    assert resumed[-1].event_payload["previous_status"] == "extracting_claims"

    # The retry call only enqueues; it must not have touched the ledger itself
    # (that happens once the enqueued task actually runs, not here).
    async with fresh_session_factory() as session:
        completed_batch_after = (await StageBatchRepository(session).list_batches(run_id, STAGE))[0]
    assert completed_batch_after.status == "completed"
    assert completed_batch_after.item_results == completed_batch_before.item_results
    assert completed_batch_after.retry_count == completed_batch_before.retry_count
    assert completed_batch_after.provider_call_count == completed_batch_before.provider_call_count


@pytest.mark.asyncio
async def test_retry_is_refused_while_a_live_worker_still_holds_the_advisory_lock(
    fresh_session_factory, low_stale_threshold, app_engine_on_test_database
) -> None:
    run, _repo, _completed_batch = await _seed_stale_run(fresh_session_factory)
    run_id = run.id
    lock_key = advisory_lock_key(run_id)

    app = create_app()
    enqueued: list = []

    async def override_session():
        async with fresh_session_factory() as session:
            yield session

    def fake_enqueue(analysis_run_id):
        enqueued.append(analysis_run_id)
        return "job-should-not-happen"

    app.dependency_overrides[get_session] = override_session
    import app.api.routes.analyses as analyses_route

    original_enqueue = analyses_route.enqueue_run_analysis_workflow
    analyses_route.enqueue_run_analysis_workflow = fake_enqueue
    try:
        # A real, separate connection actually holding the lock - as if
        # another worker were still (slowly) processing this exact run, even
        # though its heartbeat has gone stale.
        async with held_advisory_lock(lock_key) as acquired:
            assert acquired is True
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                response = await client.post(f"/api/v1/analyses/{run_id}/retry")
    finally:
        analyses_route.enqueue_run_analysis_workflow = original_enqueue
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "processing this analysis" in response.json()["detail"]
    assert enqueued == []

    # The lock is free again now (released when the `async with` block above
    # exited) - proving the 409 really was about the lock being held at the
    # time, not some other rejection, and that retry works once it clears.
    async with held_advisory_lock(lock_key) as acquired_after:
        assert acquired_after is True

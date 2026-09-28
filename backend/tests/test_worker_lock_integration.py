from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.session import held_advisory_lock
from app.repositories.comparison_repository import ComparisonRepository, advisory_lock_key
from app.repositories.processing_repository import ProcessingRepository
from app.repositories.workflow_repository import WorkflowRepository
from tests.integration_helpers import stable_uuid

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_postgres_advisory_lock_prevents_duplicate_processing(
    integration_session,
    test_database_url: str,
) -> None:
    filing_id = stable_uuid("lock-test-filing")
    second_engine = create_async_engine(test_database_url, pool_pre_ping=True)
    second_sessionmaker = async_sessionmaker(second_engine, expire_on_commit=False)

    first_repo = ProcessingRepository(integration_session)
    async with second_sessionmaker() as second_session:
        second_repo = ProcessingRepository(second_session)
        first = await first_repo.try_acquire_filing_lock(filing_id)
        second = await second_repo.try_acquire_filing_lock(filing_id)
        released = await first_repo.release_filing_lock(filing_id)
    await second_engine.dispose()

    assert first is True
    assert second is False
    assert released is True


@pytest.mark.asyncio
async def test_postgres_advisory_lock_prevents_duplicate_comparison_processing(
    integration_session,
    test_database_url: str,
) -> None:
    comparison_id = stable_uuid("lock-test-comparison")
    second_engine = create_async_engine(test_database_url, pool_pre_ping=True)
    second_sessionmaker = async_sessionmaker(second_engine, expire_on_commit=False)

    first_repo = ComparisonRepository(integration_session)
    async with second_sessionmaker() as second_session:
        second_repo = ComparisonRepository(second_session)
        first = await first_repo.try_acquire_comparison_lock(comparison_id)
        second = await second_repo.try_acquire_comparison_lock(comparison_id)
        released = await first_repo.release_comparison_lock(comparison_id)
    await second_engine.dispose()

    assert first is True
    assert second is False
    assert released is True


@pytest.mark.asyncio
async def test_held_advisory_lock_prevents_duplicate_processing_on_a_dedicated_connection(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """held_advisory_lock() (used by FilingComparisonService.process_comparison
    and the analysis-run worker tasks) must provide the same exclusivity
    guarantee as the single-session try_acquire_*_lock() pattern above, even
    though it holds the lock on its own dedicated connection instead of the
    caller's working session."""
    test_engine = create_async_engine(test_database_url, pool_pre_ping=True)
    monkeypatch.setattr("app.db.session.engine", test_engine)
    lock_key = advisory_lock_key(stable_uuid("lock-test-held-advisory"))
    try:
        async with held_advisory_lock(lock_key) as first_acquired:
            assert first_acquired is True
            async with held_advisory_lock(lock_key) as second_acquired:
                assert second_acquired is False
        # Released when the first lock's `async with` block exited; a new
        # attempt on a third, separate connection now succeeds.
        async with held_advisory_lock(lock_key) as third_acquired:
            assert third_acquired is True
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_held_advisory_lock_keepalive_survives_a_long_held_lock(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dedicated lock connection does nothing but hold the lock for
    however long the caller's actual work takes, so it must stay alive (via
    its own periodic keepalive) rather than going idle and risking being
    dropped by the database provider."""
    test_engine = create_async_engine(test_database_url, pool_pre_ping=True)
    monkeypatch.setattr("app.db.session.engine", test_engine)
    monkeypatch.setattr("app.db.session._ADVISORY_LOCK_KEEPALIVE_INTERVAL_SECONDS", 0.05)
    lock_key = advisory_lock_key(stable_uuid("lock-test-held-advisory-keepalive"))
    try:
        async with held_advisory_lock(lock_key) as acquired:
            assert acquired is True
            # Long enough for several keepalive pings; the lock must still
            # be held (and the connection still usable) afterwards.
            await asyncio.sleep(0.2)
            async with held_advisory_lock(lock_key) as still_held_elsewhere:
                assert still_held_elsewhere is False
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_advisory_lock_prevents_duplicate_analysis_run_processing(
    integration_session,
    test_database_url: str,
) -> None:
    analysis_run_id = stable_uuid("lock-test-analysis-run")
    second_engine = create_async_engine(test_database_url, pool_pre_ping=True)
    second_sessionmaker = async_sessionmaker(second_engine, expire_on_commit=False)

    first_repo = WorkflowRepository(integration_session)
    async with second_sessionmaker() as second_session:
        second_repo = WorkflowRepository(second_session)
        first = await first_repo.try_acquire_run_lock(analysis_run_id)
        second = await second_repo.try_acquire_run_lock(analysis_run_id)
        released = await first_repo.release_run_lock(analysis_run_id)
    await second_engine.dispose()

    assert first is True
    assert second is False
    assert released is True

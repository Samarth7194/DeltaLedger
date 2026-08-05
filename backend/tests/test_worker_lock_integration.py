from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.repositories.processing_repository import ProcessingRepository
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

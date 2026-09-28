from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout_seconds,
    # Defense-in-depth only: proactively discards pooled connections older
    # than this so a connection that Neon silently dropped is less likely to
    # be handed back out. The actual fix for long-held-open-transaction
    # disconnects is not holding transactions open across BGE/Gemini calls
    # in the first place (see AnalysisWorkflowService._node and
    # FilingComparisonService._process_comparison_locked).
    pool_recycle=settings.database_pool_recycle_seconds,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


_ADVISORY_LOCK_KEEPALIVE_INTERVAL_SECONDS = 60.0


@contextlib.asynccontextmanager
async def held_advisory_lock(lock_key: int) -> AsyncIterator[bool]:
    """Hold a Postgres session-level advisory lock on its own dedicated
    connection, independent of whatever connection the caller's actual work
    uses.

    Session-level advisory locks (``pg_try_advisory_lock`` /
    ``pg_advisory_unlock``) are tied to the specific physical connection
    that acquired them: closing that connection (or letting SQLAlchemy
    recycle it) silently drops the lock. Work that needs to hold such a
    lock across long external calls (BGE inference, Gemini requests) must
    therefore do that work on a *different* connection than the one holding
    the lock, since the work connection needs to be freely closed and
    reopened around that work to avoid a cloud Postgres provider (e.g.
    Neon) dropping it for sitting idle too long.

    This connection does nothing but hold the lock, so it is itself at risk
    of the same idle-drop -- a periodic no-op query keeps it alive for as
    long as the lock is held.

    Yields ``True`` if the lock was acquired (the caller should proceed) or
    ``False`` if another connection already holds it (the caller should
    skip this unit of work, exactly like the single-session
    ``try_acquire_*_lock()`` pattern this replaces for long-running work).
    """
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        acquired = bool(
            (await connection.execute(select(func.pg_try_advisory_lock(lock_key)))).scalar()
        )
        if not acquired:
            yield False
            return
        keepalive_task = asyncio.create_task(_ping_periodically(connection))
        try:
            yield True
        finally:
            keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await keepalive_task
            with contextlib.suppress(Exception):
                await connection.execute(select(func.pg_advisory_unlock(lock_key)))


async def _ping_periodically(connection: AsyncConnection) -> None:
    while True:
        await asyncio.sleep(_ADVISORY_LOCK_KEEPALIVE_INTERVAL_SECONDS)
        with contextlib.suppress(Exception):
            await connection.execute(text("SELECT 1"))

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine


def run_worker_coroutine[T](coro: Coroutine[object, object, T]) -> T:
    """Run a Dramatiq actor's top-level coroutine to completion.

    On Windows, ``asyncio.run`` defaults to the ProactorEventLoop, which
    psycopg refuses to use for async connections (the LangGraph PostgreSQL
    checkpointer's ``AsyncConnectionPool`` included). Selector-based loops
    work there instead, so Windows routes through ``asyncio.Runner`` with an
    explicit ``SelectorEventLoop`` factory. Every other platform keeps the
    standard ``asyncio.run`` behavior unchanged.

    Every call opens (and, here, closes) its own event loop, but the
    SQLAlchemy async engine's connection pool is process-global and its
    asyncpg connections are bound to the loop that created them. Without
    disposing the pool before this loop closes, a connection checked out
    under one invocation's loop gets handed to the next invocation's
    (different) loop, raising "Future attached to a different loop" /
    "Event loop is closed". Disposing here, on the same loop that used the
    pool, forces the next invocation to open fresh connections instead.
    """
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(_run_and_dispose_engine(coro))
    return asyncio.run(_run_and_dispose_engine(coro))


async def _run_and_dispose_engine[T](coro: Coroutine[object, object, T]) -> T:
    from app.db.session import engine

    try:
        return await coro
    finally:
        await engine.dispose()

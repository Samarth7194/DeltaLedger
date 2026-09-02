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
    """
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coro)
    return asyncio.run(coro)

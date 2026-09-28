from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db_url import to_sync_database_url  # noqa: E402
from tests.env_isolation import (
    SUBPROCESS_ENV_ALLOWLIST,
    assert_safe_test_database,
    isolate_settings_from_environment,
)

isolate_settings_from_environment()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    integration_skip = pytest.mark.skip(reason="set RUN_INTEGRATION_TESTS=1 to run")
    postgres_skip = pytest.mark.skip(reason="set RUN_POSTGRES_TESTS=1 to run")
    redis_skip = pytest.mark.skip(reason="set RUN_REDIS_TESTS=1 to run")
    minio_skip = pytest.mark.skip(reason="set RUN_MINIO_TESTS=1 to run")
    live_skip = pytest.mark.skip(reason="set RUN_LIVE_TESTS=1 to run")
    model_skip = pytest.mark.skip(reason="set RUN_MODEL_SMOKE=1 to run")

    for item in items:
        marker_names = {marker.name for marker in item.iter_markers()}
        if not marker_names & {
            "integration",
            "postgres",
            "redis",
            "minio",
            "live",
            "model_smoke",
            "hosted_model",
            "slow",
        }:
            item.add_marker(pytest.mark.unit)
        if "integration" in marker_names and os.getenv("RUN_INTEGRATION_TESTS") != "1":
            item.add_marker(integration_skip)
        if "postgres" in marker_names and os.getenv("RUN_POSTGRES_TESTS") != "1":
            item.add_marker(postgres_skip)
        if "redis" in marker_names and os.getenv("RUN_REDIS_TESTS") != "1":
            item.add_marker(redis_skip)
        if "minio" in marker_names and os.getenv("RUN_MINIO_TESTS") != "1":
            item.add_marker(minio_skip)
        if "live" in marker_names and os.getenv("RUN_LIVE_TESTS") != "1":
            item.add_marker(live_skip)
        model_smoke_enabled = (
            os.getenv("RUN_MODEL_SMOKE") == "1"
            or os.getenv("RUN_MODEL_SMOKE_TESTS") == "1"
        )
        if "model_smoke" in marker_names and not model_smoke_enabled:
            item.add_marker(model_skip)
        if "hosted_model" in marker_names and not model_smoke_enabled:
            item.add_marker(model_skip)

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def test_database_url() -> str:
    value = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://deltaledger@localhost:5433/deltaledger_test",
    )
    return value


@pytest.fixture(scope="session")
def safe_test_database_url(test_database_url: str) -> str:
    """The test database URL, after the destructive-test safety checks."""
    assert_safe_test_database(test_database_url)
    return test_database_url


def alembic_subprocess_env(test_database_url: str) -> dict[str, str]:
    """Environment for running alembic against the test database.

    Deliberately minimal: only what a Python subprocess needs to start
    (`SUBPROCESS_ENV_ALLOWLIST`) plus the explicit, disposable migration URL.
    None of the developer's application configuration or secrets are passed,
    and because ALEMBIC_DATABASE_URL is explicit, alembic's env.py does not
    instantiate the application Settings at all - so the developer's `.env`
    (object storage, Redis, providers, ...) is irrelevant to migrations.
    """
    env = {key: os.environ[key] for key in SUBPROCESS_ENV_ALLOWLIST if key in os.environ}
    env["ALEMBIC_DATABASE_URL"] = to_sync_database_url(test_database_url)
    return env


def run_alembic(*args: str, test_database_url: str, **kwargs):
    """Run `python -m alembic ...` against the test database from the backend dir."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        check=True,
        cwd=BACKEND_DIR,
        env=alembic_subprocess_env(test_database_url),
        **kwargs,
    )


@pytest.fixture(scope="session")
def migrated_test_database(safe_test_database_url: str) -> str:
    run_alembic("upgrade", "head", test_database_url=safe_test_database_url)
    return safe_test_database_url


@pytest.fixture
async def integration_session(migrated_test_database: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(migrated_test_database, pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
def fresh_session_factory(
    migrated_test_database: str,
) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
    """A factory that opens a genuinely NEW engine + session on every call.

    For proving durable resume: `integration_session` is one connection/one
    identity map for the whole test, so reading through it again would still
    hit the same SQLAlchemy identity map an in-memory bug could hide behind.
    Each session this factory yields is backed by its own engine (its own
    connection pool), the same way a restarted worker process would open a
    brand new one against the same persisted database.
    """

    @contextlib.asynccontextmanager
    async def _open() -> AsyncIterator[AsyncSession]:
        engine = create_async_engine(migrated_test_database, pool_pre_ping=True)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessionmaker() as session:
                yield session
        finally:
            await engine.dispose()

    return _open

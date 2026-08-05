from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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


@pytest.fixture(scope="session")
def test_database_url() -> str:
    value = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://deltaledger@localhost:5433/deltaledger_test",
    )
    return value


@pytest.fixture(scope="session")
def migrated_test_database(test_database_url: str) -> str:
    from app.core.config import get_settings

    get_settings().require_safe_test_database()
    env = {**os.environ, "DATABASE_URL": test_database_url}
    subprocess.run(["python", "-m", "alembic", "upgrade", "head"], check=True, env=env)
    return test_database_url


@pytest.fixture
async def integration_session(migrated_test_database: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(migrated_test_database, pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
        await session.rollback()
    await engine.dispose()

from __future__ import annotations

import pytest

from app.core.config import Settings


def test_local_cloud_profile_uses_filesystem_storage_and_sync_alembic_url() -> None:
    settings = Settings(
        app_profile="local-cloud",
        database_url="postgresql+asyncpg://user@db.example.com/appdb?ssl=require",
        test_database_url="postgresql+asyncpg://user@db.example.com/appdb_test?ssl=require",
        object_storage_provider="filesystem",
        embedding_provider="fake",
        reranker_provider="fake",
    )

    assert settings.alembic_database_url == (
        "postgresql+psycopg://user@db.example.com/appdb?ssl=require"
    )
    settings.require_safe_test_database()


def test_ci_profile_accepts_minio_and_service_container_urls() -> None:
    settings = Settings(
        app_profile="ci",
        database_url="postgresql+asyncpg://deltaledger@localhost:5433/deltaledger",
        test_database_url=(
            "postgresql+asyncpg://deltaledger@localhost:5433/deltaledger_test"
        ),
        object_storage_provider="minio",
        embedding_provider="fake",
        reranker_provider="fake",
    )

    assert settings.object_storage_provider == "minio"
    settings.require_safe_test_database()


def test_docker_profile_requires_internal_service_hostnames() -> None:
    Settings(
        app_profile="docker",
        database_url="postgresql+asyncpg://deltaledger@postgres:5432/deltaledger",
        test_database_url=(
            "postgresql+asyncpg://deltaledger@postgres:5432/deltaledger_test"
        ),
        redis_url="redis://redis:6379/0",
        object_storage_provider="minio",
        embedding_provider="fake",
        reranker_provider="fake",
    )

    with pytest.raises(ValueError, match="DATABASE_URL must use host"):
        Settings(
            app_profile="docker",
            database_url="postgresql+asyncpg://deltaledger@localhost:5432/deltaledger",
            test_database_url=(
                "postgresql+asyncpg://deltaledger@postgres:5432/deltaledger_test"
            ),
            redis_url="redis://redis:6379/0",
            object_storage_provider="minio",
            embedding_provider="fake",
            reranker_provider="fake",
        )


def test_destructive_test_database_safety_rejects_app_database() -> None:
    settings = Settings(
        app_profile="local-cloud",
        database_url="postgresql+asyncpg://user@db.example.com/deltaledger",
        test_database_url="postgresql+asyncpg://user@db.example.com/deltaledger",
        object_storage_provider="filesystem",
        embedding_provider="fake",
        reranker_provider="fake",
    )

    with pytest.raises(ValueError, match="must not equal"):
        settings.require_safe_test_database()

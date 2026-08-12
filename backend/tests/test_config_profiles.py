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
        "postgresql+psycopg://user@db.example.com/appdb?sslmode=require"
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


def test_local_cors_origins_are_explicit_for_frontend_development() -> None:
    settings = Settings()

    assert "http://localhost:3000" in settings.cors_origins
    assert "*" not in settings.cors_origins


def test_production_cors_rejects_wildcard_origin() -> None:
    with pytest.raises(ValueError, match="Production CORS origins"):
        Settings(environment="production", cors_allowed_origins="*")


def test_production_profile_rejects_development_fallbacks() -> None:
    with pytest.raises(ValueError, match="S3-compatible object storage"):
        Settings(
            app_profile="production",
            environment="production",
            cors_allowed_origins="https://app.example.com",
            workflow_checkpoint_provider="postgres",
            readiness_dependency_checks_enabled=True,
            sec_user_agent="DeltaLedgerAI/0.1 ops@example.com",
        )


def test_production_profile_requires_real_model_provider_or_explicit_override() -> None:
    base = {
        "app_profile": "production",
        "environment": "production",
        "cors_allowed_origins": "https://app.example.com",
        "workflow_checkpoint_provider": "postgres",
        "object_storage_provider": "minio",
        "minio_access_key": "prod-access",
        "minio_secret_key": "prod-secret",
        "sec_user_agent": "DeltaLedgerAI/0.1 ops@deltaledger.local",
        "readiness_dependency_checks_enabled": True,
        "auth_enabled": True,
        "auth_secret_key": "0123456789abcdef0123456789abcdef",
    }
    with pytest.raises(ValueError, match="Production fake model providers"):
        Settings(**base)

    settings = Settings(**base, allow_fake_models_in_production=True)

    assert settings.is_production


def test_production_profile_rejects_localhost_cors() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(
            app_profile="production",
            environment="production",
            cors_allowed_origins="http://localhost:3000",
            workflow_checkpoint_provider="postgres",
            object_storage_provider="minio",
            minio_access_key="prod-access",
            minio_secret_key="prod-secret",
            sec_user_agent="DeltaLedgerAI/0.1 ops@deltaledger.local",
            readiness_dependency_checks_enabled=True,
            allow_fake_models_in_production=True,
        )

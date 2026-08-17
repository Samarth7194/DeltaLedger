from __future__ import annotations

import pytest

from app.cli.production_doctor import mask_url, run_doctor
from app.core.config import Settings
from app.services.analysis_workflow_service import _checkpoint_conninfo


def test_mask_url_hides_passwords_and_sensitive_query_values() -> None:
    masked = mask_url(
        "postgresql+asyncpg://user:p%40ss@db.example.com:5432/app"
        "?ssl=require&token=abc&application_name=deltaledger"
    )

    assert masked == (
        "postgresql+asyncpg://user:***@db.example.com:5432/app"
        "?ssl=require&token=%2A%2A%2A&application_name=deltaledger"
    )
    assert "p%40ss" not in masked
    assert "abc" not in masked


def test_checkpoint_conninfo_preserves_url_parts_and_maps_ssl_query() -> None:
    conninfo = _checkpoint_conninfo(
        "postgresql+asyncpg://user:p%40ss@db.example.com:6543/app"
        "?ssl=require&application_name=deltaledger"
    )

    assert conninfo == (
        "postgresql://user:p%40ss@db.example.com:6543/app"
        "?sslmode=require&application_name=deltaledger"
    )


def test_alembic_url_conversion_preserves_encoded_credentials_and_query() -> None:
    settings = Settings(
        database_url=(
            "postgresql+asyncpg://user:p%40ss@db.example.com:6543/app"
            "?ssl=require&application_name=deltaledger"
        ),
        test_database_url="postgresql+asyncpg://user@db.example.com/app_test",
    )

    assert settings.alembic_database_url == (
        "postgresql+psycopg://user:p%40ss@db.example.com:6543/app"
        "?sslmode=require&application_name=deltaledger"
    )


@pytest.mark.asyncio
async def test_production_doctor_masks_runtime_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:super-secret@localhost:1/deltaledger",
    )
    monkeypatch.setenv("REDIS_URL", "redis://:redis-secret@localhost:1/0")

    payload = await run_doctor()
    rendered = str(payload)

    assert payload["status"] == "blocked"
    assert "super-secret" not in rendered
    assert "redis-secret" not in rendered
    assert "postgresql+asyncpg://user:***@localhost:1/deltaledger" in rendered
    assert "redis://:***@localhost:1/0" in rendered

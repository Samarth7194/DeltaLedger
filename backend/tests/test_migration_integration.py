from __future__ import annotations

import os
import subprocess

import pytest
from sqlalchemy import create_engine, text

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.slow]


def test_clean_database_migrates_to_head_and_schema_objects_exist(test_database_url: str) -> None:
    from app.core.config import get_settings

    get_settings().require_safe_test_database()
    env = {**os.environ, "DATABASE_URL": test_database_url}
    subprocess.run(["python", "-m", "alembic", "downgrade", "base"], check=True, env=env)
    subprocess.run(["python", "-m", "alembic", "upgrade", "head"], check=True, env=env)
    current = subprocess.run(
        ["python", "-m", "alembic", "current"],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )

    assert "0002_phase2_processing_retrieval" in current.stdout

    sync_url = test_database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    engine = create_engine(sync_url)
    with engine.connect() as connection:
        vector_ext = connection.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
        embedding_type = connection.execute(
            text(
                "SELECT format_type(a.atttypid, a.atttypmod) "
                "FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "WHERE c.relname = 'filing_chunks' AND a.attname = 'embedding'"
            )
        ).scalar_one()
        indexes = {
            row[0]
            for row in connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'filing_chunks'")
            )
        }
        tables = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename LIKE 'filing_%'"
                )
            )
        }

    assert vector_ext == 1
    assert embedding_type == "vector(1024)"
    assert "ix_filing_chunks_embedding_hnsw" in indexes
    assert "ix_filing_chunks_search_vector_gin" in indexes
    assert {"filing_tables", "filing_processing_stages"} <= tables

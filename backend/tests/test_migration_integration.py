from __future__ import annotations

import os
import subprocess

import pytest
from sqlalchemy import create_engine, text

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.slow]


def test_clean_database_migrates_to_head_and_schema_objects_exist(test_database_url: str) -> None:
    from app.core.config import get_settings

    get_settings().require_safe_test_database()
    sync_url = test_database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    env = {
        **os.environ,
        "DATABASE_URL": test_database_url,
        "ALEMBIC_DATABASE_URL": sync_url,
    }
    subprocess.run(["python", "-m", "alembic", "downgrade", "base"], check=True, env=env)
    subprocess.run(["python", "-m", "alembic", "upgrade", "head"], check=True, env=env)
    current = subprocess.run(
        ["python", "-m", "alembic", "current"],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )

    assert "0004_phase4_financial" in current.stdout

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
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
            )
        }
        disclosure_columns = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'disclosure_changes'"
                )
            )
        }
        financial_claim_columns = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'financial_claims'"
                )
            )
        }
        metric_count = connection.execute(
            text("SELECT count(*) FROM financial_metric_definitions")
        ).scalar_one()
        concept_count = connection.execute(
            text("SELECT count(*) FROM financial_metric_concepts")
        ).scalar_one()

    assert vector_ext == 1
    assert embedding_type == "vector(1024)"
    assert "ix_filing_chunks_embedding_hnsw" in indexes
    assert "ix_filing_chunks_search_vector_gin" in indexes
    assert {
        "filing_tables",
        "filing_processing_stages",
        "filing_comparisons",
        "section_matches",
        "passage_units",
        "passage_matches",
        "disclosure_changes",
        "financial_metric_definitions",
        "financial_metric_concepts",
        "financial_claims",
        "claim_fact_candidates",
        "claim_verifications",
        "derived_financial_metrics",
    } <= tables
    assert {"original_model_output", "reviewer_edits", "reviewed_by", "reviewed_at"} <= (
        disclosure_columns
    )
    assert {
        "original_model_output",
        "reviewer_edits",
        "metric_definition_id",
        "reported_change",
        "comparison_basis",
    } <= financial_claim_columns
    assert metric_count == 9
    assert concept_count == 12

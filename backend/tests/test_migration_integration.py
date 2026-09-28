from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from app.core.db_url import to_sync_database_url

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.slow]


def test_clean_database_migrates_to_head_and_schema_objects_exist(
    safe_test_database_url: str,
) -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from tests.conftest import BACKEND_DIR, run_alembic

    test_database_url = safe_test_database_url
    sync_url = to_sync_database_url(test_database_url)
    run_alembic("downgrade", "base", test_database_url=test_database_url)
    run_alembic("upgrade", "head", test_database_url=test_database_url)
    current = run_alembic(
        "current", test_database_url=test_database_url, text=True, capture_output=True
    )

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    (head,) = ScriptDirectory.from_config(config).get_heads()
    assert head in current.stdout

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
        contradiction_columns = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'contradiction_findings'"
                )
            )
        }
        analysis_run_columns = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'analysis_runs'"
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
        "contradiction_findings",
        "contradiction_evidence",
        "analysis_runs",
        "analysis_workflow_events",
        "analysis_review_requests",
        "analysis_reports",
        "analysis_stage_batches",
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
    assert {
        "finding_fingerprint",
        "severity_components",
        "confidence_components",
        "reviewer_edits",
        "original_system_finding",
    } <= contradiction_columns
    assert {
        "checkpoint_thread_id",
        "requires_human_review",
        "review_gate_reason",
        "processing_metrics",
        "input_snapshot",
    } <= analysis_run_columns
    assert metric_count == 9
    assert concept_count == 12

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=True),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("exchange", sa.String(length=64), nullable=True),
        sa.Column("industry", sa.String(length=255), nullable=True),
        sa.Column("fiscal_year_end", sa.String(length=8), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("cik", name="uq_companies_cik"),
    )
    op.create_index("ix_companies_active_ticker", "companies", ["is_active", "ticker"])
    op.create_index(
        "uq_companies_ticker_not_null",
        "companies",
        ["ticker"],
        unique=True,
        postgresql_where=sa.text("ticker IS NOT NULL"),
    )

    op.create_table(
        "filings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accession_number", sa.String(length=32), nullable=False),
        sa.Column("form_type", sa.String(length=16), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("report_period", sa.Date(), nullable=True),
        sa.Column("primary_document", sa.String(length=512), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("ingestion_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("parser_version", sa.String(length=64), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("accession_number", name="uq_filings_accession_number"),
        sa.UniqueConstraint(
            "company_id",
            "form_type",
            "report_period",
            "accession_number",
            name="uq_filings_company_form_period_accession",
        ),
    )
    op.create_index("ix_filings_company_form_period", "filings", ["company_id", "form_type", sa.text("report_period DESC")])
    op.create_index("ix_filings_ingestion_status_created", "filings", ["ingestion_status", "created_at"])
    op.create_index("ix_filings_raw_metadata_gin", "filings", ["raw_metadata"], postgresql_using="gin")

    op.create_table(
        "filing_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_type", sa.String(length=64), nullable=False),
        sa.Column("section_title", sa.String(length=512), nullable=False),
        sa.Column("section_order", sa.Integer(), nullable=False),
        sa.Column("parent_section_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_or_anchor_reference", sa.String(length=512), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_section_id"], ["filing_sections.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("filing_id", "section_order", name="uq_filing_sections_order"),
    )
    op.create_index("ix_filing_sections_filing_type_order", "filing_sections", ["filing_id", "section_type", "section_order"])
    op.create_index("ix_filing_sections_text_hash", "filing_sections", ["text_hash"])

    op.create_table(
        "filing_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filing_section_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("source_reference", sa.String(length=1024), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["filing_section_id"], ["filing_sections.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("filing_section_id", "chunk_index", name="uq_filing_chunks_section_index"),
    )
    op.create_index("ix_filing_chunks_section_index", "filing_chunks", ["filing_section_id", "chunk_index"])
    op.create_index("ix_filing_chunks_metadata_gin", "filing_chunks", ["metadata"], postgresql_using="gin")
    op.create_index(
        "ix_filing_chunks_embedding_hnsw",
        "filing_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "xbrl_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filing_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("taxonomy", sa.String(length=64), nullable=False),
        sa.Column("concept", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=512), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("value_numeric", sa.Numeric(precision=28, scale=6), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("instant_date", sa.Date(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_period", sa.String(length=16), nullable=True),
        sa.Column("form_type", sa.String(length=16), nullable=True),
        sa.Column("accession_number", sa.String(length=32), nullable=True),
        sa.Column("frame", sa.String(length=64), nullable=True),
        sa.Column("raw_fact", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["filing_id"], ["filings.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_xbrl_company_concept_fy_fp", "xbrl_facts", ["company_id", "concept", "fiscal_year", "fiscal_period"])
    op.create_index("ix_xbrl_filing_concept", "xbrl_facts", ["filing_id", "concept"])
    op.create_index("ix_xbrl_accession_concept_unit", "xbrl_facts", ["accession_number", "concept", "unit"])
    op.create_index("ix_xbrl_frame", "xbrl_facts", ["frame"])
    op.create_index("ix_xbrl_raw_fact_gin", "xbrl_facts", ["raw_fact"], postgresql_using="gin")

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("actor_type", sa.String(length=64), nullable=True),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_actor_created", "audit_events", ["actor_id", sa.text("created_at DESC")])
    op.create_index("ix_audit_entity", "audit_events", ["entity_type", "entity_id"])
    op.create_index("ix_audit_event_created", "audit_events", ["event_type", sa.text("created_at DESC")])
    op.create_index("ix_audit_metadata_gin", "audit_events", ["metadata"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("xbrl_facts")
    op.drop_table("filing_chunks")
    op.drop_table("filing_sections")
    op.drop_table("filings")
    op.drop_table("companies")
    op.execute("DROP EXTENSION IF EXISTS vector")

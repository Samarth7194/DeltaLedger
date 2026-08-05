from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_phase2_processing_retrieval"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("filing_sections", sa.Column("part_number", sa.String(length=8), nullable=True))
    op.add_column("filing_sections", sa.Column("item_number", sa.String(length=8), nullable=True))
    op.add_column(
        "filing_sections",
        sa.Column("canonical_section_type", sa.String(length=64), nullable=True),
    )
    op.add_column("filing_sections", sa.Column("raw_start_offset", sa.Integer(), nullable=True))
    op.add_column("filing_sections", sa.Column("raw_end_offset", sa.Integer(), nullable=True))
    op.add_column("filing_sections", sa.Column("normalized_start_offset", sa.Integer(), nullable=True))
    op.add_column("filing_sections", sa.Column("normalized_end_offset", sa.Integer(), nullable=True))
    op.add_column("filing_sections", sa.Column("source_anchor", sa.String(length=512), nullable=True))
    op.add_column("filing_sections", sa.Column("native_element_id", sa.String(length=512), nullable=True))
    op.add_column("filing_sections", sa.Column("dom_path", sa.String(length=1024), nullable=True))
    op.add_column("filing_sections", sa.Column("source_text_hash", sa.String(length=64), nullable=True))
    op.add_column("filing_sections", sa.Column("parser_version", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_filing_sections_part_item",
        "filing_sections",
        ["filing_id", "part_number", "item_number"],
    )

    op.create_table(
        "filing_tables",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filing_section_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("table_index", sa.Integer(), nullable=False),
        sa.Column("caption", sa.String(length=1024), nullable=True),
        sa.Column("raw_html", sa.Text(), nullable=False),
        sa.Column("normalized_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_anchor", sa.String(length=512), nullable=True),
        sa.Column("native_element_id", sa.String(length=512), nullable=True),
        sa.Column("dom_path", sa.String(length=1024), nullable=True),
        sa.Column("extraction_version", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["filing_section_id"], ["filing_sections.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("filing_id", "table_index", name="uq_filing_tables_index"),
    )
    op.create_index("ix_filing_tables_filing_section", "filing_tables", ["filing_id", "filing_section_id"])
    op.create_index("ix_filing_tables_content_hash", "filing_tables", ["content_hash"])
    op.create_index("ix_filing_tables_metadata_gin", "filing_tables", ["metadata"], postgresql_using="gin")

    op.add_column("filing_chunks", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.add_column("filing_chunks", sa.Column("source_text_hash", sa.String(length=64), nullable=True))
    op.add_column("filing_chunks", sa.Column("parser_version", sa.String(length=64), nullable=True))
    op.add_column("filing_chunks", sa.Column("chunker_version", sa.String(length=64), nullable=True))
    op.add_column("filing_chunks", sa.Column("embedding_model", sa.String(length=255), nullable=True))
    op.add_column("filing_chunks", sa.Column("embedding_version", sa.String(length=255), nullable=True))
    op.add_column("filing_chunks", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "filing_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', coalesce(text, ''))", persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_filing_chunks_content_hash", "filing_chunks", ["content_hash"])
    op.create_index(
        "ix_filing_chunks_search_vector_gin",
        "filing_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )

    op.create_table(
        "filing_processing_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("filing_id", "stage_name", name="uq_processing_stage_filing_name"),
    )
    op.create_index(
        "ix_processing_stage_filing_status",
        "filing_processing_stages",
        ["filing_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_processing_stage_filing_status", table_name="filing_processing_stages")
    op.drop_table("filing_processing_stages")

    op.drop_index("ix_filing_chunks_search_vector_gin", table_name="filing_chunks")
    op.drop_index("ix_filing_chunks_content_hash", table_name="filing_chunks")
    op.drop_column("filing_chunks", "search_vector")
    op.drop_column("filing_chunks", "embedded_at")
    op.drop_column("filing_chunks", "embedding_version")
    op.drop_column("filing_chunks", "embedding_model")
    op.drop_column("filing_chunks", "chunker_version")
    op.drop_column("filing_chunks", "parser_version")
    op.drop_column("filing_chunks", "source_text_hash")
    op.drop_column("filing_chunks", "content_hash")

    op.drop_index("ix_filing_tables_metadata_gin", table_name="filing_tables")
    op.drop_index("ix_filing_tables_content_hash", table_name="filing_tables")
    op.drop_index("ix_filing_tables_filing_section", table_name="filing_tables")
    op.drop_table("filing_tables")

    op.drop_index("ix_filing_sections_part_item", table_name="filing_sections")
    op.drop_column("filing_sections", "parser_version")
    op.drop_column("filing_sections", "source_text_hash")
    op.drop_column("filing_sections", "dom_path")
    op.drop_column("filing_sections", "native_element_id")
    op.drop_column("filing_sections", "source_anchor")
    op.drop_column("filing_sections", "normalized_end_offset")
    op.drop_column("filing_sections", "normalized_start_offset")
    op.drop_column("filing_sections", "raw_end_offset")
    op.drop_column("filing_sections", "raw_start_offset")
    op.drop_column("filing_sections", "canonical_section_type")
    op.drop_column("filing_sections", "item_number")
    op.drop_column("filing_sections", "part_number")

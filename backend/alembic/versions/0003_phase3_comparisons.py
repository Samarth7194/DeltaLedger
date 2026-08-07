from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_phase3_comparisons"
down_revision = "0002_phase2_processing_retrieval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "filing_comparisons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_filing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("comparison_filing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("comparison_version", sa.String(length=64), nullable=False),
        sa.Column("matching_model_name", sa.String(length=255), nullable=True),
        sa.Column("matching_model_version", sa.String(length=255), nullable=True),
        sa.Column("change_model_name", sa.String(length=255), nullable=True),
        sa.Column("change_model_version", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "processing_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "current_filing_id <> comparison_filing_id",
            name="ck_filing_comparisons_filing_comparison_distinct_filings",
        ),
        sa.CheckConstraint(
            "status IN ('queued','matching_sections','aligning_passages','detecting_changes','completed','failed','partial')",
            name="ck_filing_comparisons_status",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comparison_filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "current_filing_id",
            "comparison_filing_id",
            "comparison_version",
            name="uq_comparison_pair_version",
        ),
    )
    op.create_index(
        "ix_comparisons_company_pair",
        "filing_comparisons",
        ["company_id", "current_filing_id", "comparison_filing_id"],
    )

    op.create_table(
        "section_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("comparison_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_section_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("previous_section_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("match_type", sa.String(length=32), nullable=False),
        sa.Column("heading_similarity", sa.Float(), nullable=True),
        sa.Column("dense_similarity", sa.Float(), nullable=True),
        sa.Column("lexical_similarity", sa.Float(), nullable=True),
        sa.Column("reranker_score", sa.Float(), nullable=True),
        sa.Column("structural_score", sa.Float(), nullable=True),
        sa.Column("combined_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "match_reason",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("review_status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "match_type IN ('exact_structural','semantic','hybrid','unmatched_current','unmatched_previous')",
            name="ck_section_matches_match_type",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending','approved','rejected','edited')",
            name="ck_section_matches_review_status",
        ),
        sa.ForeignKeyConstraint(["comparison_id"], ["filing_comparisons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_section_id"], ["filing_sections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["previous_section_id"], ["filing_sections.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "comparison_id",
            "current_section_id",
            "previous_section_id",
            name="uq_section_match_pair",
        ),
    )
    op.create_index("ix_section_matches_comparison", "section_matches", ["comparison_id"])

    op.create_table(
        "passage_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filing_section_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unit_type", sa.String(length=32), nullable=False),
        sa.Column("unit_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("raw_char_start", sa.Integer(), nullable=False),
        sa.Column("raw_char_end", sa.Integer(), nullable=False),
        sa.Column("normalized_char_start", sa.Integer(), nullable=False),
        sa.Column("normalized_char_end", sa.Integer(), nullable=False),
        sa.Column("source_anchor", sa.String(length=512), nullable=True),
        sa.Column("source_element_id", sa.String(length=512), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("segmentation_version", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "unit_type IN ('paragraph','sentence','list_item','table_text')",
            name="ck_passage_units_unit_type",
        ),
        sa.ForeignKeyConstraint(["filing_section_id"], ["filing_sections.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "filing_section_id",
            "unit_type",
            "unit_index",
            "segmentation_version",
            name="uq_passage_unit_version",
        ),
    )
    op.create_index("ix_passage_units_section", "passage_units", ["filing_section_id", "unit_index"])

    op.create_table(
        "passage_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("section_match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_passage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("previous_passage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alignment_type", sa.String(length=32), nullable=False),
        sa.Column("dense_similarity", sa.Float(), nullable=True),
        sa.Column("lexical_similarity", sa.Float(), nullable=True),
        sa.Column("reranker_score", sa.Float(), nullable=True),
        sa.Column("sequence_score", sa.Float(), nullable=True),
        sa.Column("combined_score", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "alignment_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "alignment_type IN ('matched','added','removed','split','merged')",
            name="ck_passage_matches_alignment_type",
        ),
        sa.ForeignKeyConstraint(["section_match_id"], ["section_matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_passage_id"], ["passage_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["previous_passage_id"], ["passage_units.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "section_match_id",
            "current_passage_id",
            "previous_passage_id",
            name="uq_passage_match_pair",
        ),
    )
    op.create_index("ix_passage_matches_section_match", "passage_matches", ["section_match_id"])

    op.create_table(
        "disclosure_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("comparison_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passage_match_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("change_type", sa.String(length=32), nullable=False),
        sa.Column("risk_category", sa.String(length=64), nullable=False),
        sa.Column("previous_text", sa.Text(), nullable=True),
        sa.Column("current_text", sa.Text(), nullable=True),
        sa.Column(
            "changed_spans",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("change_explanation", sa.Text(), nullable=False),
        sa.Column("materiality_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("detection_method", sa.String(length=32), nullable=False),
        sa.Column(
            "supporting_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "materiality_components",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "original_model_output",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("model_version", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("review_status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reviewer_edits",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "change_type IN ('added','removed','strengthened','weakened','no_material_change')",
            name="ck_disclosure_changes_change_type",
        ),
        sa.CheckConstraint(
            "risk_category IN ('liquidity','revenue_guidance','litigation','other')",
            name="ck_disclosure_changes_risk_category",
        ),
        sa.CheckConstraint(
            "detection_method IN ('deterministic','model','hybrid')",
            name="ck_disclosure_changes_detection_method",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending','approved','rejected','edited','uncertain')",
            name="ck_disclosure_changes_review_status",
        ),
        sa.ForeignKeyConstraint(["comparison_id"], ["filing_comparisons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_match_id"], ["section_matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["passage_match_id"], ["passage_matches.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_disclosure_changes_type", "disclosure_changes", ["comparison_id", "change_type"])
    op.create_index("ix_disclosure_changes_risk", "disclosure_changes", ["comparison_id", "risk_category"])
    op.create_index(
        "ix_disclosure_changes_materiality",
        "disclosure_changes",
        ["comparison_id", "materiality_score"],
    )


def downgrade() -> None:
    op.drop_index("ix_disclosure_changes_materiality", table_name="disclosure_changes")
    op.drop_index("ix_disclosure_changes_risk", table_name="disclosure_changes")
    op.drop_index("ix_disclosure_changes_type", table_name="disclosure_changes")
    op.drop_table("disclosure_changes")
    op.drop_index("ix_passage_matches_section_match", table_name="passage_matches")
    op.drop_table("passage_matches")
    op.drop_index("ix_passage_units_section", table_name="passage_units")
    op.drop_table("passage_units")
    op.drop_index("ix_section_matches_comparison", table_name="section_matches")
    op.drop_table("section_matches")
    op.drop_index("ix_comparisons_company_pair", table_name="filing_comparisons")
    op.drop_table("filing_comparisons")

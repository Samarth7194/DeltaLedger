from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_phase4_financial"
down_revision = "0003_phase3_comparisons"
branch_labels = None
depends_on = None


METRICS = [
    (
        "11111111-1111-4111-8111-111111111111",
        "revenue",
        "Revenue",
        "monetary",
        "duration",
        "monetary",
        "Top-line revenue or net sales.",
        ["revenue", "revenues", "net revenue", "net revenues", "sales", "net sales", "total revenue", "total revenues"],
    ),
    (
        "22222222-2222-4222-8222-222222222222",
        "gross_profit",
        "Gross Profit",
        "monetary",
        "duration",
        "monetary",
        "Revenue less cost of revenue.",
        ["gross profit", "gross profits"],
    ),
    (
        "33333333-3333-4333-8333-333333333333",
        "gross_margin",
        "Gross Margin",
        "percentage",
        "derived",
        "percentage",
        "Gross profit divided by revenue.",
        ["gross margin", "gross profit margin", "gross profit percentage"],
    ),
    (
        "44444444-4444-4444-8444-444444444444",
        "operating_income",
        "Operating Income",
        "monetary",
        "duration",
        "monetary",
        "Income from operations.",
        ["operating income", "income from operations", "operating profit"],
    ),
    (
        "55555555-5555-4555-8555-555555555555",
        "net_income",
        "Net Income",
        "monetary",
        "duration",
        "monetary",
        "Net income or loss.",
        ["net income", "net earnings", "net loss"],
    ),
    (
        "66666666-6666-4666-8666-666666666666",
        "cash_and_cash_equivalents",
        "Cash And Cash Equivalents",
        "monetary",
        "instant",
        "monetary",
        "Cash and cash equivalents at carrying value.",
        ["cash", "cash and cash equivalents", "cash equivalents"],
    ),
    (
        "77777777-7777-4777-8777-777777777777",
        "long_term_debt",
        "Long-Term Debt",
        "monetary",
        "instant",
        "monetary",
        "Long-term debt and borrowings.",
        ["debt", "long-term debt", "long term debt", "borrowings"],
    ),
    (
        "88888888-8888-4888-8888-888888888888",
        "basic_eps",
        "Basic EPS",
        "per_share",
        "duration",
        "per_share",
        "Basic earnings per share.",
        ["basic eps", "basic earnings per share", "earnings per share basic"],
    ),
    (
        "99999999-9999-4999-8999-999999999999",
        "diluted_eps",
        "Diluted EPS",
        "per_share",
        "duration",
        "per_share",
        "Diluted earnings per share.",
        ["diluted eps", "diluted earnings per share", "earnings per share diluted"],
    ),
]


CONCEPTS = [
    ("revenue", "RevenueFromContractWithCustomerExcludingAssessedTax", 1, True),
    ("revenue", "Revenues", 2, False),
    ("revenue", "SalesRevenueNet", 3, False),
    ("gross_profit", "GrossProfit", 1, True),
    ("operating_income", "OperatingIncomeLoss", 1, True),
    ("net_income", "NetIncomeLoss", 1, True),
    ("cash_and_cash_equivalents", "CashAndCashEquivalentsAtCarryingValue", 1, True),
    ("long_term_debt", "LongTermDebtAndFinanceLeaseObligations", 1, True),
    ("long_term_debt", "LongTermDebt", 2, False),
    ("long_term_debt", "LongTermDebtCurrent", 3, False),
    ("basic_eps", "EarningsPerShareBasic", 1, True),
    ("diluted_eps", "EarningsPerShareDiluted", 1, True),
]


def upgrade() -> None:
    op.create_table(
        "financial_metric_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("canonical_name", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("metric_type", sa.String(length=32), nullable=False),
        sa.Column("period_behavior", sa.String(length=32), nullable=False),
        sa.Column("preferred_unit_category", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("metric_type IN ('monetary','percentage','ratio','per_share','count')", name="ck_financial_metric_definitions_metric_type"),
        sa.CheckConstraint("period_behavior IN ('duration','instant','derived')", name="ck_financial_metric_definitions_period_behavior"),
    )
    op.create_index("uq_financial_metric_canonical_name", "financial_metric_definitions", ["canonical_name"], unique=True)

    op.create_table(
        "financial_metric_concepts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("taxonomy", sa.String(length=64), nullable=False),
        sa.Column("concept", sa.String(length=255), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("period_behavior", sa.String(length=32), nullable=False),
        sa.Column("unit_category", sa.String(length=64), nullable=True),
        sa.Column("is_preferred", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["metric_definition_id"], ["financial_metric_definitions.id"], ondelete="CASCADE"),
        sa.CheckConstraint("period_behavior IN ('duration','instant','derived')", name="ck_financial_metric_concepts_period_behavior"),
    )
    op.create_index("ix_financial_metric_concepts_metric", "financial_metric_concepts", ["metric_definition_id", "priority"])
    op.create_index("ix_financial_metric_concepts_concept", "financial_metric_concepts", ["taxonomy", "concept"])

    op.create_table(
        "financial_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("comparison_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disclosure_change_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_section_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_passage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("canonical_metric_name", sa.String(length=128), nullable=True),
        sa.Column("metric_definition_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claim_type", sa.String(length=48), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=True),
        sa.Column("reported_value", sa.Numeric(28, 6), nullable=True),
        sa.Column("reported_unit", sa.String(length=64), nullable=True),
        sa.Column("reported_change", sa.Numeric(28, 6), nullable=True),
        sa.Column("reported_change_unit", sa.String(length=32), nullable=True),
        sa.Column("comparison_basis", sa.String(length=48), nullable=True),
        sa.Column("comparison_text", sa.Text(), nullable=True),
        sa.Column("qualifiers", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("extraction_confidence", sa.Numeric(6, 4), nullable=False),
        sa.Column("extraction_method", sa.String(length=32), nullable=False),
        sa.Column("original_model_output", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("model_version", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("review_status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_edits", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comparison_id"], ["filing_comparisons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["disclosure_change_id"], ["disclosure_changes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_section_id"], ["filing_sections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_passage_id"], ["passage_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["metric_definition_id"], ["financial_metric_definitions.id"], ondelete="SET NULL"),
        sa.CheckConstraint("claim_type IN ('absolute_value','directional_change','percentage_change','percentage_point_change','ratio_change','comparative_statement','qualitative_financial_claim')", name="ck_financial_claims_claim_type"),
        sa.CheckConstraint("direction IS NULL OR direction IN ('increase','decrease','unchanged','positive','negative','unknown')", name="ck_financial_claims_direction"),
        sa.CheckConstraint("reported_change_unit IS NULL OR reported_change_unit IN ('percent','percentage_points','absolute','basis_points')", name="ck_financial_claims_reported_change_unit"),
        sa.CheckConstraint("comparison_basis IS NULL OR comparison_basis IN ('prior_quarter','prior_year_quarter','year_to_date','prior_year_ytd','same_period_prior_year','unspecified')", name="ck_financial_claims_comparison_basis"),
        sa.CheckConstraint("extraction_method IN ('deterministic','model','hybrid')", name="ck_financial_claims_extraction_method"),
        sa.CheckConstraint("review_status IN ('pending','approved','rejected','edited','uncertain')", name="ck_financial_claims_review_status"),
    )
    op.create_index("ix_financial_claims_filing_metric", "financial_claims", ["filing_id", "canonical_metric_name"])
    op.create_index("ix_financial_claims_comparison", "financial_claims", ["comparison_id"])
    op.create_index("ix_financial_claims_source_passage", "financial_claims", ["source_passage_id"])

    op.create_table(
        "claim_fact_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("financial_claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("xbrl_fact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_role", sa.String(length=32), nullable=False),
        sa.Column("concept_priority", sa.Integer(), nullable=False),
        sa.Column("concept_match_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("period_match_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("unit_match_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("accession_match_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("frame_match_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("combined_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("selection_status", sa.String(length=32), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["financial_claim_id"], ["financial_claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["xbrl_fact_id"], ["xbrl_facts.id"], ondelete="CASCADE"),
        sa.CheckConstraint("candidate_role IN ('current','comparison')", name="ck_claim_fact_candidates_role"),
        sa.CheckConstraint("selection_status IN ('candidate','selected','rejected','ambiguous')", name="ck_claim_fact_candidates_status"),
    )
    op.create_index("ix_claim_fact_candidates_claim_role", "claim_fact_candidates", ["financial_claim_id", "candidate_role"])
    op.create_index("ix_claim_fact_candidates_fact", "claim_fact_candidates", ["xbrl_fact_id"])

    op.create_table(
        "claim_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("financial_claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_xbrl_fact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("comparison_xbrl_fact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verification_status", sa.String(length=48), nullable=False),
        sa.Column("current_value", sa.Numeric(28, 6), nullable=True),
        sa.Column("comparison_value", sa.Numeric(28, 6), nullable=True),
        sa.Column("absolute_change", sa.Numeric(28, 6), nullable=True),
        sa.Column("percentage_change", sa.Numeric(28, 6), nullable=True),
        sa.Column("percentage_point_change", sa.Numeric(28, 6), nullable=True),
        sa.Column("reported_change", sa.Numeric(28, 6), nullable=True),
        sa.Column("reported_vs_calculated_difference", sa.Numeric(28, 6), nullable=True),
        sa.Column("calculation_type", sa.String(length=64), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("calculation_inputs", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("calculation_output", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("tolerance_used", sa.Numeric(28, 6), nullable=True),
        sa.Column("verification_reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 4), nullable=False),
        sa.Column("verification_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["financial_claim_id"], ["financial_claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_xbrl_fact_id"], ["xbrl_facts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["comparison_xbrl_fact_id"], ["xbrl_facts.id"], ondelete="SET NULL"),
        sa.CheckConstraint("verification_status IN ('verified','approximately_verified','contradicted','insufficient_data','ambiguous_metric','ambiguous_fact','unsupported_metric','period_mismatch','unit_mismatch','accession_mismatch','zero_denominator','calculation_error')", name="ck_claim_verifications_status"),
    )
    op.create_index("uq_claim_verifications_claim_version", "claim_verifications", ["financial_claim_id", "verification_version"], unique=True)
    op.create_index("ix_claim_verifications_status", "claim_verifications", ["verification_status"])

    op.create_table(
        "derived_financial_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calculation_status", sa.String(length=48), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("input_fact_ids", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("calculation_inputs_snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("calculated_value", sa.Numeric(28, 6), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("period_type", sa.String(length=48), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("calculation_version", sa.String(length=64), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["metric_definition_id"], ["financial_metric_definitions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.CheckConstraint("calculation_status IN ('calculated','insufficient_inputs','ambiguous_inputs','period_mismatch','unit_mismatch','zero_denominator')", name="ck_derived_financial_metrics_status"),
    )
    op.create_index("ix_derived_metrics_filing_metric", "derived_financial_metrics", ["filing_id", "metric_definition_id"])
    op.create_index("ix_derived_metrics_period", "derived_financial_metrics", ["filing_id", "period_start", "period_end"])
    op.create_index(
        "uq_derived_metrics_filing_metric_period_version",
        "derived_financial_metrics",
        ["filing_id", "metric_definition_id", "period_start", "period_end", "calculation_version"],
        unique=True,
    )
    _seed_metric_registry()


def downgrade() -> None:
    op.drop_index("uq_derived_metrics_filing_metric_period_version", table_name="derived_financial_metrics")
    op.drop_index("ix_derived_metrics_period", table_name="derived_financial_metrics")
    op.drop_index("ix_derived_metrics_filing_metric", table_name="derived_financial_metrics")
    op.drop_table("derived_financial_metrics")
    op.drop_index("ix_claim_verifications_status", table_name="claim_verifications")
    op.drop_index("uq_claim_verifications_claim_version", table_name="claim_verifications")
    op.drop_table("claim_verifications")
    op.drop_index("ix_claim_fact_candidates_fact", table_name="claim_fact_candidates")
    op.drop_index("ix_claim_fact_candidates_claim_role", table_name="claim_fact_candidates")
    op.drop_table("claim_fact_candidates")
    op.drop_index("ix_financial_claims_source_passage", table_name="financial_claims")
    op.drop_index("ix_financial_claims_comparison", table_name="financial_claims")
    op.drop_index("ix_financial_claims_filing_metric", table_name="financial_claims")
    op.drop_table("financial_claims")
    op.drop_index("ix_financial_metric_concepts_concept", table_name="financial_metric_concepts")
    op.drop_index("ix_financial_metric_concepts_metric", table_name="financial_metric_concepts")
    op.drop_table("financial_metric_concepts")
    op.drop_index("uq_financial_metric_canonical_name", table_name="financial_metric_definitions")
    op.drop_table("financial_metric_definitions")


def _seed_metric_registry() -> None:
    metric_ids = {canonical: metric_id for metric_id, canonical, *_ in METRICS}
    metric_rows = [
        "("
        f"{_cast(_sql(metric_id), 'UUID')}, {_sql(canonical)}, {_sql(display)}, "
        f"{_sql(metric_type)}, {_sql(period_behavior)}, {_sql(unit_category)}, "
        f"{_sql(description)}, {_jsonb(aliases)}, true"
        ")"
        for metric_id, canonical, display, metric_type, period_behavior, unit_category, description, aliases in METRICS
    ]
    op.execute(
        sa.text(
            "INSERT INTO financial_metric_definitions "
            "(id, canonical_name, display_name, metric_type, period_behavior, "
            "preferred_unit_category, description, aliases, is_active) VALUES "
            + ", ".join(metric_rows)
        )
    )

    concept_rows = [
        "("
        f"{_cast(_sql(f'aaaaaaaa-aaaa-4aaa-8aaa-{index:012d}'), 'UUID')}, "
        f"{_cast(_sql(metric_ids[canonical]), 'UUID')}, "
        f"'us-gaap', {_sql(concept)}, {priority}, "
        f"{_sql(_period_behavior(canonical))}, {_sql(_unit_category(canonical))}, "
        f"{str(is_preferred).lower()}, true, 'Seeded Phase 4 MVP concept mapping.'"
        ")"
        for index, (canonical, concept, priority, is_preferred) in enumerate(CONCEPTS, start=1)
    ]
    op.execute(
        sa.text(
            "INSERT INTO financial_metric_concepts "
            "(id, metric_definition_id, taxonomy, concept, priority, period_behavior, "
            "unit_category, is_preferred, is_active, notes) VALUES "
            + ", ".join(concept_rows)
        )
    )


def _sql(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _jsonb(value: object) -> str:
    return _cast(_sql(json.dumps(value, separators=(",", ":"))), "JSONB")


def _cast(value: str, sql_type: str) -> str:
    return f"CAST({value} AS {sql_type})"


def _period_behavior(canonical: str) -> str:
    return "instant" if canonical in {"cash_and_cash_equivalents", "long_term_debt"} else "duration"


def _unit_category(canonical: str) -> str:
    if canonical in {"basic_eps", "diluted_eps"}:
        return "per_share"
    return "monetary"

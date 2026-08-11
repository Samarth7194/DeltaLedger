from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    AnalysisReport,
    AnalysisReviewRequest,
    AnalysisRun,
    AnalysisWorkflowEvent,
    ClaimVerification,
    Company,
    ContradictionEvidence,
    ContradictionFinding,
    DisclosureChange,
    Filing,
    FilingChunk,
    FilingComparison,
    FilingSection,
    FinancialClaim,
    PassageMatch,
    PassageUnit,
    SectionMatch,
    XbrlFact,
)
from app.demo.dataset import DEMO_TICKER, build_demo_manifest

DEMO_NAMESPACE = uuid.UUID("41bb06ed-bf28-4ad4-b9ce-342eb27fc51f")


async def seed_offline_demo(
    session: AsyncSession,
    settings: Settings,
    *,
    reset: bool = False,
) -> dict[str, Any]:
    if reset:
        if settings.is_production:
            raise ValueError("Refusing to reset demo data in production.")
        await reset_offline_demo(session)
    existing = await session.scalar(select(Company).where(Company.ticker == DEMO_TICKER))
    if existing is not None:
        return {"status": "already_exists", "company_id": str(existing.id)}

    manifest = build_demo_manifest()
    company = Company(
        id=_id("company"),
        cik=manifest["company"]["cik"],
        ticker=DEMO_TICKER,
        legal_name=manifest["company"]["legal_name"],
        industry=manifest["company"]["industry"],
        exchange="Demo",
        fiscal_year_end="1231",
        is_active=True,
    )
    session.add(company)
    previous_filing = _filing(company.id, manifest["filings"]["previous"], "previous")
    current_filing = _filing(company.id, manifest["filings"]["current"], "current")
    session.add_all([previous_filing, current_filing])
    await session.flush()

    previous_sections = _sections(previous_filing, manifest["filings"]["previous"])
    current_sections = _sections(current_filing, manifest["filings"]["current"])
    session.add_all([*previous_sections, *current_sections])
    await session.flush()

    previous_passage = _passage(previous_sections[0], "previous-liquidity")
    current_passage = _passage(current_sections[0], "current-liquidity")
    claim_passage = _passage(current_sections[1], "current-revenue")
    chunks = [
        _chunk(previous_sections[0], 0),
        _chunk(current_sections[0], 0),
        _chunk(current_sections[1], 0),
    ]
    session.add_all([previous_passage, current_passage, claim_passage, *chunks])
    await session.flush()

    previous_fact = _revenue_fact(company.id, previous_filing, Decimal("1000.000000"), "previous")
    current_fact = _revenue_fact(company.id, current_filing, Decimal("1040.000000"), "current")
    session.add_all([previous_fact, current_fact])
    await session.flush()

    comparison = FilingComparison(
        id=_id("comparison"),
        company_id=company.id,
        current_filing_id=current_filing.id,
        comparison_filing_id=previous_filing.id,
        status="completed",
        comparison_version=settings.comparison_version,
        matching_model_name="deterministic-demo",
        matching_model_version="demo-v1",
        change_model_name=settings.change_classifier_model,
        change_model_version=settings.comparison_version,
        processing_metrics={"demo": True},
    )
    session.add(comparison)
    await session.flush()

    section_match = SectionMatch(
        id=_id("section-match-liquidity"),
        comparison_id=comparison.id,
        current_section_id=current_sections[0].id,
        previous_section_id=previous_sections[0].id,
        match_type="hybrid",
        heading_similarity=1.0,
        dense_similarity=0.89,
        lexical_similarity=0.77,
        structural_score=1.0,
        combined_score=0.91,
        confidence=0.92,
        match_reason={"demo": "same Part II Item 1A liquidity language"},
    )
    session.add(section_match)
    await session.flush()

    passage_match = PassageMatch(
        id=_id("passage-match-liquidity"),
        section_match_id=section_match.id,
        current_passage_id=current_passage.id,
        previous_passage_id=previous_passage.id,
        alignment_type="matched",
        dense_similarity=0.84,
        lexical_similarity=0.70,
        sequence_score=1.0,
        combined_score=0.84,
        confidence=0.88,
        alignment_metadata={"demo": True},
    )
    disclosure_change = DisclosureChange(
        id=_id("disclosure-change-liquidity"),
        comparison_id=comparison.id,
        section_match_id=section_match.id,
        passage_match_id=passage_match.id,
        change_type="weakened",
        risk_category="liquidity",
        previous_text=previous_passage.text,
        current_text=current_passage.text,
        changed_spans=[
            {"text": "access to external financing", "reason": "new financing dependency"},
            {"text": "subject to market conditions", "reason": "new uncertainty qualifier"},
        ],
        change_summary=manifest["expected_outputs"]["disclosure_change"]["summary"],
        change_explanation="The current filing introduces external financing dependence.",
        materiality_score=0.78,
        confidence=0.86,
        detection_method="deterministic",
        supporting_evidence={"current_passage_id": str(current_passage.id)},
        materiality_components={"risk": 0.8, "uncertainty": 0.7},
        original_model_output={"demo": True},
    )
    session.add_all([passage_match, disclosure_change])
    await session.flush()

    claim = FinancialClaim(
        id=_id("financial-claim-revenue"),
        filing_id=current_filing.id,
        comparison_id=comparison.id,
        disclosure_change_id=disclosure_change.id,
        source_section_id=current_sections[1].id,
        source_passage_id=claim_passage.id,
        claim_text=manifest["expected_outputs"]["financial_claim"]["claim_text"],
        canonical_metric_name="revenue",
        claim_type="change_percent",
        direction="increased",
        reported_change=Decimal("12.000000"),
        reported_change_unit="percent",
        comparison_basis="prior_year_quarter",
        comparison_text="compared with the prior-year quarter",
        qualifiers={"demo": True},
        extraction_confidence=Decimal("0.9400"),
        extraction_method="deterministic",
        original_model_output={"demo": True},
        model_name=settings.claim_extractor_model,
        model_version=settings.financial_verification_version,
    )
    session.add(claim)
    await session.flush()

    verification = ClaimVerification(
        id=_id("claim-verification-revenue"),
        financial_claim_id=claim.id,
        current_xbrl_fact_id=current_fact.id,
        comparison_xbrl_fact_id=previous_fact.id,
        verification_status="contradicted",
        current_value=Decimal("1040.000000"),
        comparison_value=Decimal("1000.000000"),
        absolute_change=Decimal("40.000000"),
        percentage_change=Decimal("4.000000"),
        reported_change=Decimal("12.000000"),
        reported_vs_calculated_difference=Decimal("8.000000"),
        calculation_type="percentage_change",
        formula="(current - comparison) / comparison * 100",
        calculation_inputs={
            "current_xbrl_fact_id": str(current_fact.id),
            "comparison_xbrl_fact_id": str(previous_fact.id),
        },
        calculation_output={"percentage_change": "4.000000"},
        tolerance_used=Decimal("0.250000"),
        verification_reason="Reported 12% revenue growth does not match XBRL-derived 4%.",
        confidence=Decimal("0.9700"),
        verification_version=settings.financial_verification_version,
    )
    session.add(verification)
    await session.flush()

    finding = ContradictionFinding(
        id=_id("contradiction-revenue-overstatement"),
        company_id=company.id,
        comparison_id=comparison.id,
        financial_claim_id=claim.id,
        claim_verification_id=verification.id,
        disclosure_change_id=disclosure_change.id,
        contradiction_type="magnitude_overstatement",
        status="confirmed_for_review",
        risk_category="revenue_guidance",
        severity="high",
        confidence=Decimal("0.9300"),
        narrative_claim=claim.claim_text,
        narrative_direction="increased",
        measured_direction="increased",
        reported_value=Decimal("12.000000"),
        calculated_value=Decimal("4.000000"),
        calculated_change=Decimal("4.000000"),
        difference=Decimal("8.000000"),
        finding_title="Revenue growth claim exceeds XBRL-derived change",
        finding_summary="The filing says revenue increased 12%, while matched facts imply 4%.",
        finding_explanation=(
            "The discrepancy is deterministic and should be reviewed by an analyst."
        ),
        limitations=["Demo data is synthetic/reduced-real."],
        deterministic_evidence={"claim_verification_id": str(verification.id)},
        supporting_evidence={"disclosure_change_id": str(disclosure_change.id)},
        severity_components={"difference_pp": "8.000000"},
        confidence_components={"xbrl_match": "0.9700"},
        detection_method="deterministic",
        rule_ids=["demo-revenue-growth-overstatement"],
        finding_fingerprint=_fingerprint("demo-revenue-overstatement"),
        review_status="approved",
        review_comment="Approved during deterministic demo setup.",
        reviewed_by="demo-reviewer",
        reviewed_at=datetime.now(UTC),
    )
    session.add(finding)
    await session.flush()

    session.add_all(
        [
            _evidence(
                finding.id,
                "current_passage",
                current_filing.id,
                current_sections[0].id,
                current_passage.id,
            ),
            _evidence(
                finding.id,
                "previous_passage",
                previous_filing.id,
                previous_sections[0].id,
                previous_passage.id,
            ),
            _evidence(
                finding.id,
                "financial_claim",
                current_filing.id,
                current_sections[1].id,
                claim_passage.id,
                claim.id,
            ),
            _evidence(
                finding.id,
                "claim_verification",
                current_filing.id,
                current_sections[1].id,
                claim_passage.id,
                claim.id,
                verification.id,
            ),
            _evidence(
                finding.id,
                "xbrl_fact",
                current_filing.id,
                None,
                None,
                claim.id,
                verification.id,
                current_fact.id,
            ),
        ]
    )
    await session.flush()

    run = AnalysisRun(
        id=_id("analysis-run"),
        company_id=company.id,
        current_filing_id=current_filing.id,
        comparison_filing_id=previous_filing.id,
        comparison_id=comparison.id,
        status="completed_with_warnings",
        workflow_version=settings.analysis_workflow_version,
        graph_version=settings.analysis_graph_version,
        checkpoint_thread_id="demo-analysis-thread-v1",
        requires_human_review=True,
        review_gate_reason={"reason": "High-severity potential inconsistency required review."},
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        processing_metrics={"demo": True, "completed_nodes": ["review_gate", "generate_report"]},
        input_snapshot={"demo": True},
    )
    session.add(run)
    await session.flush()

    review = AnalysisReviewRequest(
        id=_id("review-request"),
        analysis_run_id=run.id,
        review_type="contradiction_review",
        status="approved",
        reason="High-severity potential inconsistency required review.",
        finding_ids=[str(finding.id)],
        claim_ids=[str(claim.id)],
        verification_ids=[str(verification.id)],
        requested_at=datetime.now(UTC),
        reviewed_at=datetime.now(UTC),
        reviewed_by="demo-reviewer",
        review_comment="Approved for demo report generation.",
        review_payload={"demo": True},
    )
    session.add(review)
    session.add_all(
        [
            _event(run.id, "workflow_started"),
            _event(run.id, "review_requested", node_name="review_gate"),
            _event(run.id, "review_completed", node_name="review_gate"),
            _event(run.id, "report_generated", node_name="generate_report"),
            _event(run.id, "workflow_completed", node_name="finalize_analysis"),
        ]
    )
    report = AnalysisReport(
        id=_id("analysis-report"),
        analysis_run_id=run.id,
        report_version=settings.analysis_report_version,
        status="finalized",
        executive_summary=(
            "Demo analysis found one liquidity wording change and one evidence-backed "
            "potential revenue-growth inconsistency."
        ),
        comparison_summary={"comparison_id": str(comparison.id), "disclosure_changes": 1},
        disclosure_change_summary={"weakened": 1},
        financial_verification_summary={"contradicted": 1},
        contradiction_summary={"total_candidates": 1, "by_type": {"magnitude_overstatement": 1}},
        high_priority_findings=[{"finding_id": str(finding.id), "severity": "high"}],
        limitations=manifest["limitations"],
        evidence_manifest={
            "disclosure_change_ids": [str(disclosure_change.id)],
            "financial_claim_ids": [str(claim.id)],
            "claim_verification_ids": [str(verification.id)],
            "contradiction_finding_ids": [str(finding.id)],
        },
        report_payload={"demo": manifest},
        generator_name="deterministic-demo-report",
        generator_version=settings.analysis_report_version,
        generated_at=datetime.now(UTC),
        finalized_at=datetime.now(UTC),
        content_hash=_fingerprint("demo-report"),
    )
    session.add(report)
    await session.commit()
    return {
        "status": "created",
        "company_id": str(company.id),
        "current_filing_id": str(current_filing.id),
        "comparison_filing_id": str(previous_filing.id),
        "analysis_run_id": str(run.id),
        "report_id": str(report.id),
    }


async def reset_offline_demo(session: AsyncSession) -> None:
    company = await session.scalar(select(Company).where(Company.ticker == DEMO_TICKER))
    if company is None:
        return
    run_ids = list(
        (
            await session.scalars(
                select(AnalysisRun.id).where(AnalysisRun.company_id == company.id)
            )
        ).all()
    )
    comparison_ids = list(
        (
            await session.scalars(
                select(FilingComparison.id).where(FilingComparison.company_id == company.id)
            )
        ).all()
    )
    finding_ids = list(
        (
            await session.scalars(
                select(ContradictionFinding.id).where(ContradictionFinding.company_id == company.id)
            )
        ).all()
    )
    if finding_ids:
        await session.execute(
            delete(ContradictionEvidence).where(
                ContradictionEvidence.contradiction_finding_id.in_(finding_ids)
            )
        )
        await session.execute(
            delete(ContradictionFinding).where(ContradictionFinding.id.in_(finding_ids))
        )
    if run_ids:
        await session.execute(
            delete(AnalysisReport).where(AnalysisReport.analysis_run_id.in_(run_ids))
        )
        await session.execute(
            delete(AnalysisReviewRequest).where(AnalysisReviewRequest.analysis_run_id.in_(run_ids))
        )
        await session.execute(
            delete(AnalysisWorkflowEvent).where(AnalysisWorkflowEvent.analysis_run_id.in_(run_ids))
        )
        await session.execute(delete(AnalysisRun).where(AnalysisRun.id.in_(run_ids)))
    if comparison_ids:
        claim_ids = list(
            (
                await session.scalars(
                    select(FinancialClaim.id).where(FinancialClaim.comparison_id.in_(comparison_ids))
                )
            ).all()
        )
        if claim_ids:
            await session.execute(
                delete(ClaimVerification).where(ClaimVerification.financial_claim_id.in_(claim_ids))
            )
            await session.execute(delete(FinancialClaim).where(FinancialClaim.id.in_(claim_ids)))
        await session.execute(
            delete(DisclosureChange).where(DisclosureChange.comparison_id.in_(comparison_ids))
        )
        section_match_ids = list(
            (
                await session.scalars(
                    select(SectionMatch.id).where(SectionMatch.comparison_id.in_(comparison_ids))
                )
            ).all()
        )
        if section_match_ids:
            await session.execute(
                delete(PassageMatch).where(PassageMatch.section_match_id.in_(section_match_ids))
            )
            await session.execute(
                delete(SectionMatch).where(SectionMatch.id.in_(section_match_ids))
            )
        await session.execute(
            delete(FilingComparison).where(FilingComparison.id.in_(comparison_ids))
        )
    filing_ids = list(
        (
            await session.scalars(select(Filing.id).where(Filing.company_id == company.id))
        ).all()
    )
    if filing_ids:
        section_ids = list(
            (
                await session.scalars(
                    select(FilingSection.id).where(FilingSection.filing_id.in_(filing_ids))
                )
            ).all()
        )
        if section_ids:
            await session.execute(
                delete(FilingChunk).where(FilingChunk.filing_section_id.in_(section_ids))
            )
            await session.execute(
                delete(PassageUnit).where(PassageUnit.filing_section_id.in_(section_ids))
            )
            await session.execute(
                delete(FilingSection).where(FilingSection.id.in_(section_ids))
            )
        await session.execute(delete(XbrlFact).where(XbrlFact.filing_id.in_(filing_ids)))
        await session.execute(delete(Filing).where(Filing.id.in_(filing_ids)))
    await session.execute(delete(Company).where(Company.id == company.id))
    await session.commit()


def _id(name: str) -> uuid.UUID:
    return uuid.uuid5(DEMO_NAMESPACE, name)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _filing(company_id: uuid.UUID, payload: dict[str, str], label: str) -> Filing:
    accession = payload["accession_number"]
    return Filing(
        id=_id(f"filing-{label}"),
        company_id=company_id,
        accession_number=accession,
        form_type="10-Q",
        filing_date=datetime.fromisoformat(payload["filing_date"]).date(),
        report_period=datetime.fromisoformat(payload["report_period"]).date(),
        primary_document=f"{accession}.htm",
        source_url=f"demo://filings/{accession}",
        storage_key=f"demo/{accession}.htm",
        content_hash=_fingerprint(accession),
        ingestion_status="processed",
        parser_version="demo-parser-v1",
        raw_metadata={"demo": True, "source_type": "synthetic_reduced_real"},
    )


def _sections(filing: Filing, payload: dict[str, str]) -> list[FilingSection]:
    return [
        _section(filing, "liquidity", 1, payload["liquidity_text"]),
        _section(filing, "mdna", 2, payload["revenue_text"]),
    ]


def _section(filing: Filing, section_type: str, order: int, text: str) -> FilingSection:
    return FilingSection(
        id=_id(f"section-{filing.accession_number}-{section_type}"),
        filing_id=filing.id,
        section_type=section_type,
        part_number="II",
        item_number="1A" if section_type == "liquidity" else "2",
        canonical_section_type=section_type,
        section_title=(
            "Liquidity and Capital Resources"
            if section_type == "liquidity"
            else "Management Discussion and Analysis"
        ),
        section_order=order,
        raw_text=text,
        normalized_text=text.lower(),
        text_hash=_fingerprint(text),
        token_count=len(text.split()),
        source_anchor=f"demo-{section_type}",
        source_text_hash=_fingerprint(text),
        parser_version="demo-parser-v1",
        metadata_={"demo": True},
    )


def _passage(section: FilingSection, name: str) -> PassageUnit:
    return PassageUnit(
        id=_id(f"passage-{name}"),
        filing_section_id=section.id,
        unit_type="paragraph",
        unit_index=0,
        text=section.raw_text,
        normalized_text=section.normalized_text,
        raw_char_start=0,
        raw_char_end=len(section.raw_text),
        normalized_char_start=0,
        normalized_char_end=len(section.normalized_text),
        source_anchor=section.source_anchor,
        content_hash=section.text_hash,
        segmentation_version="demo-segmentation-v1",
        metadata_={"demo": True},
    )


def _chunk(section: FilingSection, index: int) -> FilingChunk:
    return FilingChunk(
        id=_id(f"chunk-{section.id}-{index}"),
        filing_section_id=section.id,
        chunk_index=index,
        text=section.raw_text,
        token_count=section.token_count,
        start_offset=0,
        end_offset=len(section.raw_text),
        source_reference=f"{section.source_anchor}#chunk-{index}",
        content_hash=section.text_hash,
        source_text_hash=section.source_text_hash,
        parser_version=section.parser_version,
        chunker_version="demo-chunker-v1",
        metadata_={"demo": True},
    )


def _revenue_fact(
    company_id: uuid.UUID,
    filing: Filing,
    value: Decimal,
    label: str,
) -> XbrlFact:
    return XbrlFact(
        id=_id(f"xbrl-revenue-{label}"),
        company_id=company_id,
        filing_id=filing.id,
        taxonomy="us-gaap",
        concept="RevenueFromContractWithCustomerExcludingAssessedTax",
        label="Revenue",
        unit="USD",
        value_numeric=value,
        start_date=filing.report_period.replace(month=max(1, filing.report_period.month - 2)),
        end_date=filing.report_period,
        fiscal_year=filing.report_period.year,
        fiscal_period="Q2" if label == "current" else "Q1",
        form_type="10-Q",
        accession_number=filing.accession_number,
        frame=(
            f"CY{filing.report_period.year}Q2"
            if label == "current"
            else f"CY{filing.report_period.year}Q1"
        ),
        raw_fact={"demo": True, "value": str(value)},
    )


def _evidence(
    finding_id: uuid.UUID,
    evidence_type: str,
    filing_id: uuid.UUID,
    section_id: uuid.UUID | None,
    passage_id: uuid.UUID | None,
    claim_id: uuid.UUID | None = None,
    verification_id: uuid.UUID | None = None,
    xbrl_fact_id: uuid.UUID | None = None,
) -> ContradictionEvidence:
    return ContradictionEvidence(
        id=_id(f"evidence-{evidence_type}"),
        contradiction_finding_id=finding_id,
        evidence_type=evidence_type,
        filing_id=filing_id,
        section_id=section_id,
        passage_id=passage_id,
        xbrl_fact_id=xbrl_fact_id,
        financial_claim_id=claim_id,
        claim_verification_id=verification_id,
        source_text="demo evidence",
        source_hash=_fingerprint(evidence_type),
        source_anchor=f"demo://{evidence_type}",
        evidence_role=(
            "primary"
            if evidence_type in {"claim_verification", "financial_claim"}
            else "supporting"
        ),
        metadata_={"demo": True},
    )


def _event(
    analysis_run_id: uuid.UUID,
    event_type: str,
    *,
    node_name: str | None = None,
) -> AnalysisWorkflowEvent:
    return AnalysisWorkflowEvent(
        id=_id(f"event-{event_type}-{node_name or 'workflow'}"),
        analysis_run_id=analysis_run_id,
        event_type=event_type,
        node_name=node_name,
        event_payload={"demo": True},
    )

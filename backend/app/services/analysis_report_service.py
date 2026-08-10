from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    AnalysisReport,
    ClaimVerification,
    Company,
    ContradictionEvidence,
    ContradictionFinding,
    DisclosureChange,
    Filing,
    FinancialClaim,
)
from app.repositories.contradiction_repository import ContradictionRepository
from app.repositories.workflow_repository import WorkflowRepository


class AnalysisReportService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.workflow = WorkflowRepository(session)
        self.contradictions = ContradictionRepository(session)

    async def generate_report(self, analysis_run_id: uuid.UUID) -> AnalysisReport:
        run = await self.workflow.get_run(analysis_run_id)
        if run is None:
            raise ValueError(f"Analysis run not found: {analysis_run_id}")
        company = await self.session.get(Company, run.company_id)
        current = await self.session.get(Filing, run.current_filing_id)
        previous = await self.session.get(Filing, run.comparison_filing_id)
        changes = await _scalars(
            self.session,
            select(DisclosureChange).where(DisclosureChange.comparison_id == run.comparison_id),
        )
        verifications = await _scalars(
            self.session,
            select(ClaimVerification)
            .join(FinancialClaim)
            .where(FinancialClaim.comparison_id == run.comparison_id),
        )
        findings = await self.contradictions.list_findings(
            comparison_id=run.comparison_id,
            limit=1000,
        )
        evidence = await _scalars(
            self.session,
            select(ContradictionEvidence).join(
                ContradictionFinding,
                ContradictionEvidence.contradiction_finding_id == ContradictionFinding.id,
            ).where(ContradictionFinding.comparison_id == run.comparison_id),
        )
        contradiction_summary = await self.contradictions.summarize_findings(run.comparison_id)
        disclosure_summary = _counts_by(changes, "change_type")
        verification_summary = _counts_by(verifications, "verification_status")
        high_priority = [
            {
                "finding_id": str(finding.id),
                "contradiction_type": finding.contradiction_type,
                "severity": finding.severity,
                "confidence": str(finding.confidence),
                "review_status": finding.review_status,
                "evidence_ids": [
                    str(item.id)
                    for item in evidence
                    if item.contradiction_finding_id == finding.id
                ],
            }
            for finding in findings
            if finding.severity in {"high", "critical"} and finding.review_status != "rejected"
        ]
        limitations = _limitations(verifications, findings, run)
        manifest = _evidence_manifest(changes, verifications, findings, evidence)
        payload = {
            "company": {
                "id": str(company.id) if company else str(run.company_id),
                "ticker": company.ticker if company else None,
                "legal_name": company.legal_name if company else None,
            },
            "filings": {
                "current_filing_id": str(run.current_filing_id),
                "comparison_filing_id": str(run.comparison_filing_id),
                "current_accession": current.accession_number if current else None,
                "comparison_accession": previous.accession_number if previous else None,
            },
            "analysis": {
                "analysis_run_id": str(run.id),
                "workflow_version": run.workflow_version,
                "graph_version": run.graph_version,
                "comparison_id": str(run.comparison_id) if run.comparison_id else None,
            },
            "comparison_summary": {
                "comparison_id": str(run.comparison_id) if run.comparison_id else None,
                "disclosure_changes": len(changes),
            },
            "disclosure_change_summary": disclosure_summary,
            "financial_verification_summary": verification_summary,
            "contradiction_summary": contradiction_summary,
            "high_priority_findings": high_priority,
            "limitations": limitations,
            "evidence_manifest": manifest,
        }
        content_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        report = AnalysisReport(
            analysis_run_id=run.id,
            report_version=self.settings.analysis_report_version,
            status="finalized",
            executive_summary=_summary(
                disclosure_summary,
                verification_summary,
                contradiction_summary,
            ),
            comparison_summary=payload["comparison_summary"],
            disclosure_change_summary=disclosure_summary,
            financial_verification_summary=verification_summary,
            contradiction_summary=contradiction_summary,
            high_priority_findings=high_priority,
            limitations=limitations,
            evidence_manifest=manifest,
            report_payload=payload,
            generator_name="deterministic-analysis-report",
            generator_version=self.settings.analysis_report_version,
            prompt_version=None,
            generated_at=datetime.now(UTC),
            finalized_at=datetime.now(UTC),
            content_hash=content_hash,
        )
        return await self.workflow.upsert_report(report)


async def _scalars(session: AsyncSession, stmt) -> list[Any]:
    return list((await session.scalars(stmt)).all())


def _counts_by(items: list[object], attr: str) -> dict[str, int]:
    return dict(Counter(str(getattr(item, attr)) for item in items))


def _limitations(
    verifications: list[ClaimVerification],
    findings: list[ContradictionFinding],
    run: object,
) -> list[str]:
    values: list[str] = []
    unresolved = [
        item
        for item in verifications
        if item.verification_status
        not in {"verified", "approximately_verified", "contradicted"}
    ]
    if unresolved:
        values.append("Some financial claims remain unresolved or ambiguous.")
    if any(finding.status == "insufficient_evidence" for finding in findings):
        values.append("Some contradiction candidates have incomplete evidence.")
    if any(finding.review_status == "uncertain" for finding in findings):
        values.append("One or more findings were marked uncertain during review.")
    if getattr(run, "requires_human_review", False):
        values.append("Workflow-level human review was required for this analysis.")
    return values


def _evidence_manifest(
    changes: list[DisclosureChange],
    verifications: list[ClaimVerification],
    findings: list[ContradictionFinding],
    evidence: list[ContradictionEvidence],
) -> dict[str, list[str]]:
    return {
        "disclosure_change_ids": [str(item.id) for item in changes],
        "financial_claim_ids": sorted(
            {str(item.financial_claim_id) for item in verifications}
        ),
        "claim_verification_ids": [str(item.id) for item in verifications],
        "contradiction_finding_ids": [str(item.id) for item in findings],
        "contradiction_evidence_ids": [str(item.id) for item in evidence],
        "xbrl_fact_ids": sorted(
            {
                str(value)
                for item in verifications
                for value in (item.current_xbrl_fact_id, item.comparison_xbrl_fact_id)
                if value is not None
            }
        ),
        "section_ids": sorted({str(item.section_id) for item in evidence if item.section_id}),
        "passage_ids": sorted({str(item.passage_id) for item in evidence if item.passage_id}),
    }


def _summary(
    disclosure_summary: dict[str, int],
    verification_summary: dict[str, int],
    contradiction_summary: dict[str, Any],
) -> str:
    return (
        "Analysis completed with "
        f"{sum(disclosure_summary.values())} disclosure changes, "
        f"{sum(verification_summary.values())} financial claim verifications, and "
        f"{contradiction_summary.get('total_candidates', 0)} potential inconsistency candidates."
    )

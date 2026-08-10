from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.ai.financial_claims import DeterministicFakeClaimExtractor
from app.core.config import Settings
from app.db.models import ContradictionFinding, FilingSection, PassageUnit
from app.db.session import get_session
from app.main import create_app
from app.repositories.contradiction_repository import ContradictionRepository
from app.services.contradiction_analysis_service import ContradictionAnalysisService
from app.services.financial_claim_extraction_service import FinancialClaimExtractionService
from app.services.financial_claim_verification_service import FinancialClaimVerificationService
from tests.integration_helpers import create_financial_verification_corpus

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_phase5_contradiction_analysis_persists_idempotent_candidates_and_api(
    integration_session,
) -> None:
    corpus = await create_financial_verification_corpus(integration_session)
    settings = Settings(
        app_profile="local-cloud",
        claim_extractor_provider="fake",
        contradiction_classifier_provider="fake",
        xbrl_fact_min_score=0.75,
        xbrl_fact_ambiguity_margin=0.05,
    )
    section = await integration_session.get(FilingSection, corpus["current_section_id"])
    passage = await integration_session.get(PassageUnit, corpus["current_passage_id"])
    assert section is not None
    assert passage is not None

    claims = await FinancialClaimExtractionService(
        integration_session,
        settings,
        DeterministicFakeClaimExtractor(),
    ).extract_from_passage(
        filing_id=corpus["current_filing_id"],
        source_section=section,
        passage=passage,
        text=passage.text,
        comparison_id=corpus["comparison_id"],
    )
    percentage_claim = next(claim for claim in claims if claim.claim_type == "percentage_change")
    percentage_claim.reported_change = Decimal("20.000000")
    percentage_claim.claim_text = "Revenue increased 20% compared with the same period last year."
    verification = await FinancialClaimVerificationService(
        integration_session,
        settings,
    ).verify_claim(percentage_claim.id)
    await integration_session.commit()
    assert verification.verification_status == "contradicted"

    service = ContradictionAnalysisService(integration_session, settings)
    first = await service.analyze_comparison(corpus["comparison_id"])
    second = await service.analyze_comparison(corpus["comparison_id"])

    assert first["created"] == 1
    assert second["updated"] == 1
    finding_count = await integration_session.scalar(select(func.count(ContradictionFinding.id)))
    assert finding_count == 1

    repo = ContradictionRepository(integration_session)
    findings = await repo.list_findings(comparison_id=corpus["comparison_id"])
    finding = findings[0]
    evidence = await repo.list_evidence(finding.id)
    assert finding.contradiction_type == "numerical_claim_contradiction"
    assert finding.status == "candidate"
    assert finding.review_status == "pending"
    assert any(item.evidence_role == "primary" for item in evidence)

    app = create_app()

    async def override_session():
        yield integration_session

    app.dependency_overrides[get_session] = override_session
    from app.api.routes import contradictions

    original_enqueue = contradictions.enqueue_analyze_contradictions
    contradictions.enqueue_analyze_contradictions = lambda _comparison_id: "contradiction-job-test"
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            analyze_response = await client.post(
                f"/api/v1/comparisons/{corpus['comparison_id']}/contradictions/analyze"
            )
            list_response = await client.get(
                f"/api/v1/comparisons/{corpus['comparison_id']}/contradictions"
            )
            summary_response = await client.get(
                f"/api/v1/comparisons/{corpus['comparison_id']}/contradiction-summary"
            )
            detail_response = await client.get(f"/api/v1/contradictions/{finding.id}")
            evidence_response = await client.get(f"/api/v1/contradictions/{finding.id}/evidence")
            review_response = await client.patch(
                f"/api/v1/contradictions/{finding.id}/review",
                json={
                    "review_status": "edited",
                    "comment": "Adjusted after analyst review.",
                    "reviewer_id": "analyst@example.com",
                    "severity": "medium",
                    "summary": "Reviewed numerical inconsistency candidate.",
                },
            )
    finally:
        contradictions.enqueue_analyze_contradictions = original_enqueue
        app.dependency_overrides.clear()

    assert analyze_response.status_code == 202
    assert analyze_response.json()["data"]["job_id"] == "contradiction-job-test"
    assert list_response.status_code == 200
    assert len(list_response.json()["data"]) == 1
    assert summary_response.status_code == 200
    assert summary_response.json()["data"]["total_candidates"] == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["calculation"]["percentage_change"] == "12.0000"
    assert evidence_response.status_code == 200
    assert any(item["evidence_role"] == "primary" for item in evidence_response.json()["data"])
    assert review_response.status_code == 200
    reviewed = review_response.json()["data"]
    assert reviewed["review_status"] == "edited"
    assert reviewed["severity"] == "medium"
    assert reviewed["reviewer_edits"]["severity"] == "high"

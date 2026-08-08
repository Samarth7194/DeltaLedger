from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.ai.financial_claims import DeterministicFakeClaimExtractor
from app.core.config import Settings
from app.db.models import ClaimVerification, FilingSection, PassageUnit, XbrlFact
from app.db.session import get_session
from app.main import create_app
from app.repositories.financial_repository import FinancialRepository
from app.services.derived_financial_metric_service import DerivedFinancialMetricService
from app.services.financial_claim_extraction_service import FinancialClaimExtractionService
from app.services.financial_claim_verification_service import FinancialClaimVerificationService
from tests.integration_helpers import create_financial_verification_corpus

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_phase4_financial_claims_verify_against_real_xbrl_and_api(
    integration_session,
) -> None:
    corpus = await create_financial_verification_corpus(integration_session)
    settings = Settings(
        app_profile="local-cloud",
        claim_extractor_provider="fake",
        xbrl_fact_min_score=0.75,
        xbrl_fact_ambiguity_margin=0.05,
    )
    section = await integration_session.get(FilingSection, corpus["current_section_id"])
    passage = await integration_session.get(PassageUnit, corpus["current_passage_id"])
    assert section is not None
    assert passage is not None

    extraction_service = FinancialClaimExtractionService(
        integration_session,
        settings,
        DeterministicFakeClaimExtractor(),
    )
    claims = await extraction_service.extract_from_passage(
        filing_id=corpus["current_filing_id"],
        source_section=section,
        passage=passage,
        text=passage.text,
        comparison_id=corpus["comparison_id"],
    )
    duplicate_claims = await extraction_service.extract_from_passage(
        filing_id=corpus["current_filing_id"],
        source_section=section,
        passage=passage,
        text=passage.text,
        comparison_id=corpus["comparison_id"],
    )
    assert len(claims) == len(duplicate_claims) == 3

    percentage_claim = next(claim for claim in claims if claim.claim_type == "percentage_change")
    verification_service = FinancialClaimVerificationService(integration_session, settings)
    first_verification = await verification_service.verify_claim(percentage_claim.id)
    second_verification = await verification_service.verify_claim(percentage_claim.id)
    await integration_session.commit()

    verification_count = await integration_session.scalar(
        select(func.count(ClaimVerification.id)).where(
            ClaimVerification.financial_claim_id == percentage_claim.id
        )
    )
    assert first_verification.id == second_verification.id
    assert verification_count == 1
    assert first_verification.verification_status == "verified"
    assert first_verification.current_value == Decimal("112000000.000000")
    assert first_verification.comparison_value == Decimal("100000000.000000")
    assert first_verification.percentage_change == Decimal("12.000000")

    candidates = await FinancialRepository(integration_session).list_fact_candidates(
        percentage_claim.id
    )
    assert {candidate.candidate_role for candidate in candidates} == {"current", "comparison"}
    selected_current = [
        candidate
        for candidate in candidates
        if candidate.candidate_role == "current" and candidate.selection_status == "selected"
    ]
    assert len(selected_current) == 1
    assert selected_current[0].xbrl_fact_id == corpus["current_revenue_fact_id"]

    current_filing = await FinancialRepository(integration_session).get_filing(
        corpus["current_filing_id"]
    )
    current_revenue = await integration_session.get(XbrlFact, corpus["current_revenue_fact_id"])
    current_gross_profit = await integration_session.get(
        XbrlFact,
        corpus["current_gross_profit_fact_id"],
    )
    assert current_filing is not None
    gross_margin = await DerivedFinancialMetricService(
        integration_session,
        settings,
    ).calculate_gross_margin(
        filing=current_filing,
        revenue_fact=current_revenue,
        gross_profit_fact=current_gross_profit,
    )
    await integration_session.commit()
    assert gross_margin.calculation_status == "calculated"
    assert gross_margin.calculated_value == Decimal("40.000000")

    app = create_app()

    async def override_session():
        yield integration_session

    app.dependency_overrides[get_session] = override_session
    from app.api.routes import financial

    original_extract = financial.enqueue_extract_financial_claims
    original_verify = financial.enqueue_verify_financial_claim
    financial.enqueue_extract_financial_claims = lambda _filing_id: "extract-job-test"
    financial.enqueue_verify_financial_claim = lambda _claim_id: "verify-job-test"
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            extract_response = await client.post(
                f"/api/v1/filings/{corpus['current_filing_id']}/financial-claims/extract"
            )
            list_response = await client.get(
                f"/api/v1/filings/{corpus['current_filing_id']}/financial-claims"
            )
            verify_response = await client.post(
                f"/api/v1/financial-claims/{percentage_claim.id}/verify"
            )
            candidates_response = await client.get(
                f"/api/v1/financial-claims/{percentage_claim.id}/fact-candidates"
            )
            selected_candidate_id = next(
                item["id"]
                for item in candidates_response.json()["data"]
                if item["candidate_role"] == "current"
                and item["selection_status"] == "selected"
            )
            candidate_review_response = await client.patch(
                "/api/v1/financial-claims/"
                f"{percentage_claim.id}/fact-candidates/{selected_candidate_id}/review",
                json={
                    "reviewer_id": "analyst@example.com",
                    "comment": "Confirmed current revenue fact.",
                },
            )
            verification_response = await client.get(
                f"/api/v1/financial-claims/{percentage_claim.id}/verification"
            )
            comparison_claims_response = await client.get(
                f"/api/v1/comparisons/{corpus['comparison_id']}/financial-claims"
            )
            comparison_verifications_response = await client.get(
                f"/api/v1/comparisons/{corpus['comparison_id']}/financial-verifications"
            )
            review_response = await client.patch(
                f"/api/v1/financial-claims/{percentage_claim.id}/review",
                json={
                    "review_status": "edited",
                    "comment": "Reviewed reported percentage.",
                    "reviewer_id": "analyst@example.com",
                    "reported_value": "12.0",
                },
            )
    finally:
        financial.enqueue_extract_financial_claims = original_extract
        financial.enqueue_verify_financial_claim = original_verify
        app.dependency_overrides.clear()

    assert extract_response.status_code == 202
    assert extract_response.json()["data"]["job_id"] == "extract-job-test"
    assert verify_response.status_code == 202
    assert verify_response.json()["data"]["job_id"] == "verify-job-test"
    assert list_response.status_code == 200
    assert len(list_response.json()["data"]) == 3
    assert candidates_response.status_code == 200
    assert any(
        item["selection_status"] == "selected"
        for item in candidates_response.json()["data"]
    )
    assert candidate_review_response.status_code == 200
    assert candidate_review_response.json()["data"]["selection_status"] == "selected"
    assert "Reviewer selected candidate" in (
        candidate_review_response.json()["data"]["rejection_reason"]
    )
    assert verification_response.status_code == 200
    assert verification_response.json()["data"]["verification_status"] == "verified"
    assert comparison_claims_response.status_code == 200
    assert len(comparison_claims_response.json()["data"]) == 3
    assert comparison_verifications_response.status_code == 200
    assert len(comparison_verifications_response.json()["data"]) == 1
    assert review_response.status_code == 200
    reviewed = review_response.json()["data"]
    assert reviewed["review_status"] == "edited"
    assert reviewed["review_comment"] == "Reviewed reported percentage."
    assert reviewed["original_model_output"]["claim_text"] == percentage_claim.claim_text
    assert reviewed["reviewer_edits"]["reported_value"] == str(
        percentage_claim.reported_value
    )

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.db.session import get_session
from app.main import create_app
from app.repositories.comparison_repository import ComparisonRepository
from app.services.filing_comparison_service import FilingComparisonService
from tests.integration_helpers import create_comparison_corpus

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_phase3_comparison_pipeline_persists_api_visible_results(
    integration_session,
) -> None:
    corpus = await create_comparison_corpus(integration_session)
    settings = Settings(
        app_profile="local-cloud",
        embedding_provider="fake",
        reranker_enabled=True,
        reranker_provider="fake",
        change_classifier_provider="fake",
    )
    app = create_app()

    async def override_session():
        yield integration_session

    app.dependency_overrides[get_session] = override_session
    from app.api.routes import comparisons

    original_enqueue = comparisons.enqueue_process_comparison
    original_get_settings = comparisons.get_settings
    comparisons.enqueue_process_comparison = lambda _comparison_id: "comparison-job-test"
    comparisons.get_settings = lambda: settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            create_response = await client.post(
                "/api/v1/comparisons",
                json={
                    "current_filing_id": str(corpus["current_filing_id"]),
                    "comparison_filing_id": str(corpus["comparison_filing_id"]),
                },
            )
            assert create_response.status_code == 202
            comparison_id = create_response.json()["data"]["comparison_id"]

            await FilingComparisonService(integration_session, settings).process_comparison(
                UUID(comparison_id)
            )

            summary_response = await client.get(f"/api/v1/comparisons/{comparison_id}")
            sections_response = await client.get(
                f"/api/v1/comparisons/{comparison_id}/section-matches"
            )
            passages_response = await client.get(
                f"/api/v1/comparisons/{comparison_id}/passage-matches"
            )
            changes_response = await client.get(
                f"/api/v1/comparisons/{comparison_id}/changes",
                params={"min_materiality": 0.0},
            )
            changes_payload = changes_response.json()["data"]
            edited_change = next(
                change for change in changes_payload if change["change_type"] == "weakened"
            )
            review_response = await client.patch(
                f"/api/v1/comparisons/{comparison_id}/changes/{edited_change['id']}/review",
                json={
                    "review_status": "edited",
                    "comment": "Risk category reviewed.",
                    "reviewer_id": "analyst@example.com",
                    "risk_category": "other",
                    "summary": "Reviewed liquidity language change.",
                },
            )
    finally:
        comparisons.enqueue_process_comparison = original_enqueue
        comparisons.get_settings = original_get_settings
        app.dependency_overrides.clear()

    assert summary_response.status_code == 200
    summary = summary_response.json()["data"]
    assert summary["status"] == "completed"
    assert summary["processing_metrics"]["sections_matched"] == 1
    assert summary["summary_counts"]["weakened"] >= 1
    assert sections_response.status_code == 200
    assert sections_response.json()["data"][0]["match_type"] == "exact_structural"
    assert passages_response.status_code == 200
    assert {item["alignment_type"] for item in passages_response.json()["data"]} >= {
        "matched",
        "added",
    }
    assert changes_response.status_code == 200
    change_types = {change["change_type"] for change in changes_payload}
    assert {"added", "strengthened", "weakened", "no_material_change"} <= change_types
    assert edited_change["supporting_evidence"]["current"]["section_id"] == str(
        corpus["current_section_id"]
    )
    assert review_response.status_code == 200
    reviewed = review_response.json()["data"]
    assert reviewed["review_status"] == "edited"
    assert reviewed["risk_category"] == "other"
    assert reviewed["original_model_output"]["risk_category"] == "liquidity"
    assert reviewed["reviewer_edits"]["risk_category"] == "liquidity"


@pytest.mark.asyncio
async def test_create_comparison_rejects_invalid_filing_order(integration_session) -> None:
    corpus = await create_comparison_corpus(integration_session)
    service = FilingComparisonService(integration_session, Settings(app_profile="local-cloud"))

    with pytest.raises(Exception, match="Current filing period must be later"):
        await service.create_comparison(
            current_filing_id=corpus["comparison_filing_id"],
            comparison_filing_id=corpus["current_filing_id"],
        )


@pytest.mark.asyncio
async def test_comparison_pair_creation_is_idempotent(integration_session) -> None:
    corpus = await create_comparison_corpus(integration_session)
    service = FilingComparisonService(integration_session, Settings(app_profile="local-cloud"))

    first = await service.create_comparison(
        current_filing_id=corpus["current_filing_id"],
        comparison_filing_id=corpus["comparison_filing_id"],
    )
    second = await service.create_comparison(
        current_filing_id=corpus["current_filing_id"],
        comparison_filing_id=corpus["comparison_filing_id"],
    )
    repo = ComparisonRepository(integration_session)
    comparisons = await repo.list_comparisons(company_id=corpus["company_id"])

    assert first.comparison_id == second.comparison_id
    assert first.created is True
    assert second.created is False
    assert len(comparisons) == 1

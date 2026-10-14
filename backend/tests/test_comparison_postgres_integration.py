from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.db.models import DisclosureChange, FilingComparison, SectionMatch
from app.db.session import get_session
from app.main import create_app
from app.repositories.comparison_repository import ComparisonRepository
from app.services.filing_comparison_service import FilingComparisonService
from tests.integration_helpers import create_comparison_corpus

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_reusable_change_results_are_scoped_to_model_and_prompt_version(
    integration_session,
) -> None:
    """The retry-resumability fix: a prior classification is only eligible
    for reuse when it was produced by the exact same classifier
    model/prompt version as the current attempt. A stale row from a
    different model or prompt version must never be silently reused."""
    corpus = await create_comparison_corpus(integration_session)
    comparison = FilingComparison(
        company_id=corpus["company_id"],
        current_filing_id=corpus["current_filing_id"],
        comparison_filing_id=corpus["comparison_filing_id"],
        comparison_version="test-v1",
        status="matching_sections",
        processing_metrics={},
    )
    integration_session.add(comparison)
    await integration_session.flush()

    section_match = SectionMatch(
        comparison_id=comparison.id,
        current_section_id=corpus["current_section_id"],
        previous_section_id=corpus["previous_section_id"],
        match_type="exact_structural",
        combined_score=0.9,
        confidence=0.9,
        match_reason={},
    )
    integration_session.add(section_match)
    await integration_session.flush()

    def _change(*, previous_text, current_text, model_name, model_version, prompt_version):
        return DisclosureChange(
            comparison_id=comparison.id,
            section_match_id=section_match.id,
            change_type="weakened",
            risk_category="liquidity",
            previous_text=previous_text,
            current_text=current_text,
            changed_spans=[],
            change_summary="s",
            change_explanation="e",
            materiality_score=0.5,
            confidence=0.8,
            detection_method="hybrid",
            supporting_evidence={},
            materiality_components={},
            original_model_output={
                "change_type": "weakened",
                "summary": "s",
                "explanation": "e",
                "changed_spans": [],
                "confidence": 0.8,
                "risk_category": "liquidity",
                "materiality_reason": "mr",
            },
            model_name=model_name,
            model_version=model_version,
            prompt_version=prompt_version,
        )

    matching = _change(
        previous_text="matching previous",
        current_text="matching current",
        model_name="gemini-3.5-flash-lite",
        model_version="gemini-3.5-flash-lite",
        prompt_version="disclosure-change-json-v2",
    )
    stale_prompt_version = _change(
        previous_text="stale previous",
        current_text="stale current",
        model_name="gemini-3.5-flash-lite",
        model_version="gemini-3.5-flash-lite",
        prompt_version="disclosure-change-json-v1",
    )
    stale_model = _change(
        previous_text="other model previous",
        current_text="other model current",
        model_name="gemini-2.5-flash",
        model_version="gemini-2.5-flash",
        prompt_version="disclosure-change-json-v2",
    )
    integration_session.add_all([matching, stale_prompt_version, stale_model])
    await integration_session.commit()

    repo = ComparisonRepository(integration_session)
    reusable = await repo.list_reusable_change_results(
        comparison.id,
        model_name="gemini-3.5-flash-lite",
        prompt_version="disclosure-change-json-v2",
    )

    assert reusable == [("matching previous", "matching current", matching.original_model_output)]


@pytest.mark.asyncio
async def test_phase3_comparison_pipeline_persists_api_visible_results(
    integration_session,
    fresh_session_factory,
    monkeypatch,
) -> None:
    corpus = await create_comparison_corpus(integration_session)
    # API overrides do not redirect the dedicated advisory-lock connection.
    monkeypatch.setattr("app.db.session.engine", integration_session.bind)
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

            await FilingComparisonService(
                integration_session, settings, session_factory=fresh_session_factory
            ).process_comparison(UUID(comparison_id))

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

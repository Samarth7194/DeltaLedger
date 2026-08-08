from decimal import Decimal
from uuid import uuid4

from app.core.config import Settings
from app.db.models import ClaimFactCandidate
from app.services.xbrl_fact_resolution_service import XbrlFactResolutionService, units_compatible


def candidate(score: str, *, unit_score: str = "1", period_score: str = "1") -> ClaimFactCandidate:
    return ClaimFactCandidate(
        financial_claim_id=uuid4(),
        xbrl_fact_id=uuid4(),
        candidate_role="current",
        concept_priority=1,
        concept_match_score=Decimal("1"),
        period_match_score=Decimal(period_score),
        unit_match_score=Decimal(unit_score),
        accession_match_score=Decimal("1"),
        frame_match_score=Decimal("1"),
        combined_score=Decimal(score),
        selection_status="candidate",
    )


def selector() -> XbrlFactResolutionService:
    service = XbrlFactResolutionService.__new__(XbrlFactResolutionService)
    service.settings = Settings(
        app_profile="local-cloud",
        xbrl_fact_min_score=0.75,
        xbrl_fact_ambiguity_margin=0.05,
    )
    return service


def test_units_compatible_by_category() -> None:
    assert units_compatible("monetary", "USD") is True
    assert units_compatible("monetary", "shares") is False
    assert units_compatible("per_share", "USD/share") is True
    assert units_compatible("percentage", "pure") is True


def test_select_rejects_wrong_unit_or_period_even_with_high_score() -> None:
    service = selector()

    assert service._select([candidate("0.90", unit_score="0")]) is None
    assert service._select([candidate("0.90", period_score="0")]) is None


def test_select_rejects_ambiguous_candidates_and_marks_both() -> None:
    service = selector()
    first = candidate("0.9100")
    second = candidate("0.8900")

    selected = service._select([first, second])

    assert selected is None
    assert first.selection_status == "ambiguous"
    assert second.selection_status == "ambiguous"


def test_select_accepts_clear_highest_candidate() -> None:
    service = selector()
    first = candidate("0.9200")
    second = candidate("0.8000")

    selected = service._select([first, second])

    assert selected is first
    assert first.selection_status == "selected"
    assert second.selection_status == "rejected"

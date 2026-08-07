from __future__ import annotations

import pytest

from app.ai.embeddings import DeterministicFakeEmbeddingProvider, EmbeddingService
from app.ai.reranker import DeterministicFakeReranker
from app.ai.semantic_change import DeterministicFakeChangeClassifier
from app.core.config import Settings
from app.db.models import FilingSection, PassageMatch, PassageUnit, SectionMatch
from app.services.disclosure_change_service import DisclosureChangeService
from app.services.evaluation_metrics import macro_f1, phase3_metrics, precision_recall_f1
from app.services.passage_alignment_service import PassageAlignmentService
from app.services.passage_segmentation_service import PassageSegmentationService
from app.services.section_matching_service import SectionMatchingService
from tests.integration_helpers import stable_uuid


def _settings(**overrides) -> Settings:
    return Settings(
        app_profile="local-cloud",
        embedding_provider="fake",
        reranker_enabled=True,
        reranker_provider="fake",
        **overrides,
    )


def _section(
    key: str,
    *,
    order: int = 0,
    title: str = "Item 2. Management Discussion",
    text: str = "Liquidity remained sufficient.",
    canonical_type: str = "mda",
    item: str = "2",
) -> FilingSection:
    return FilingSection(
        id=stable_uuid(key),
        filing_id=stable_uuid(f"{key}-filing"),
        section_type=canonical_type,
        canonical_section_type=canonical_type,
        part_number="I",
        item_number=item,
        section_title=title,
        section_order=order,
        raw_text=text,
        normalized_text=text.lower(),
        text_hash=key,
        token_count=len(text.split()),
        source_anchor=f"#{key}",
        metadata_={},
    )


def _passage(key: str, text: str, index: int) -> PassageUnit:
    return PassageUnit(
        id=stable_uuid(key),
        filing_section_id=stable_uuid(f"{key}-section"),
        unit_type="paragraph",
        unit_index=index,
        text=text,
        normalized_text=text.lower(),
        raw_char_start=0,
        raw_char_end=len(text),
        normalized_char_start=0,
        normalized_char_end=len(text),
        source_anchor=f"#{key}",
        content_hash=key,
        segmentation_version="test-v1",
        metadata_={},
    )


def _embedding_service() -> EmbeddingService:
    return EmbeddingService(
        DeterministicFakeEmbeddingProvider(dimension=1024),
        expected_dimension=1024,
        batch_size=4,
    )


def test_passage_segmentation_preserves_order_offsets_and_hashes() -> None:
    section = _section(
        "seg-section",
        text=(
            "Liquidity remained sufficient.\n\n"
            "We may need additional financing if demand declines."
        ),
    )
    units = PassageSegmentationService(_settings()).segment_section(section)

    assert [unit.unit_index for unit in units] == [0, 1]
    assert units[0].text == "Liquidity remained sufficient."
    assert units[1].raw_char_start > units[0].raw_char_end
    assert units[0].content_hash != units[1].content_hash
    assert units[0].source_anchor == "#seg-section"


@pytest.mark.asyncio
async def test_section_matching_combines_structural_dense_lexical_and_reranker_scores() -> None:
    current = _section("current-mda", text="Liquidity and revenue demand improved.", order=0)
    previous = _section("previous-mda", text="Liquidity and revenue demand was stable.", order=0)
    unrelated = _section(
        "previous-risk",
        title="Item 1A. Legal Proceedings",
        text="A lawsuit was settled.",
        canonical_type="legal",
        item="1A",
        order=1,
    )
    service = SectionMatchingService(_settings(), _embedding_service(), DeterministicFakeReranker())

    matches = await service.match_sections(
        comparison_id=stable_uuid("comparison"),
        current_sections=[current],
        previous_sections=[previous, unrelated],
    )

    assert matches[0].match_type in {"exact_structural", "hybrid"}
    assert matches[0].current_section_id == current.id
    assert matches[0].previous_section_id == previous.id
    assert matches[0].structural_score == 1.0
    assert matches[0].dense_similarity is not None
    assert matches[0].reranker_score is not None
    assert matches[1].match_type == "unmatched_previous"


@pytest.mark.asyncio
async def test_passage_alignment_returns_monotonic_matches_and_additions() -> None:
    previous = [_passage("prev-liquidity", "Liquidity remained sufficient.", 0)]
    current = [
        _passage("curr-liquidity", "Liquidity remained sufficient.", 0),
        _passage("curr-new", "We may need additional financing if demand declines.", 1),
    ]
    service = PassageAlignmentService(
        _settings(),
        _embedding_service(),
        DeterministicFakeReranker(),
    )

    matches = await service.align_passages(
        section_match_id=stable_uuid("section-match"),
        current_passages=current,
        previous_passages=previous,
    )

    assert [match.alignment_type for match in matches] == ["matched", "added"]
    assert matches[0].combined_score is not None
    assert matches[0].alignment_metadata["strategy"] == "monotonic_dynamic_programming"


@pytest.mark.asyncio
async def test_disclosure_change_detection_preserves_evidence_and_materiality_components() -> None:
    previous_section = _section("prev-section", text="We will maintain sufficient liquidity.")
    current_section = _section(
        "curr-section",
        text="We may need additional financing if demand declines.",
    )
    previous = _passage("prev-passage", previous_section.raw_text, 0)
    current = _passage("curr-passage", current_section.raw_text, 0)
    section_match = SectionMatch(
        id=stable_uuid("section-match"),
        comparison_id=stable_uuid("comparison"),
        current_section_id=current_section.id,
        previous_section_id=previous_section.id,
        match_type="exact_structural",
        combined_score=0.9,
        confidence=0.9,
        match_reason={},
    )
    passage_match = PassageMatch(
        id=stable_uuid("passage-match"),
        section_match_id=section_match.id,
        current_passage_id=current.id,
        previous_passage_id=previous.id,
        alignment_type="matched",
        combined_score=0.7,
        confidence=0.7,
        alignment_metadata={},
    )
    service = DisclosureChangeService(_settings(), DeterministicFakeChangeClassifier())

    change = await service.detect_change(
        comparison_id=stable_uuid("comparison"),
        section_match=section_match,
        passage_match=passage_match,
        current_passage=current,
        previous_passage=previous,
        current_section=current_section,
        previous_section=previous_section,
    )

    assert change is not None
    assert change.change_type == "weakened"
    assert change.risk_category == "liquidity"
    assert change.supporting_evidence["current"]["passage_id"] == str(current.id)
    assert change.supporting_evidence["previous"]["passage_id"] == str(previous.id)
    assert change.original_model_output["change_type"] == "weakened"
    assert change.materiality_components["materiality_score"] == change.materiality_score


def test_phase3_evaluation_metrics_report_macro_scores() -> None:
    metrics = precision_recall_f1(
        ["added", "removed", "weakened", "weakened"],
        ["added", "weakened", "weakened", "removed"],
    )

    assert metrics["added"].precision == 1.0
    assert metrics["removed"].recall == 0.0
    assert macro_f1(metrics) == 0.5

    summary = phase3_metrics(
        [
            {
                "expected_change_type": "added",
                "predicted_change_type": "added",
                "expected_risk_category": "liquidity",
                "predicted_risk_category": "liquidity",
            }
        ]
    )
    assert summary["count"] == 1
    assert summary["change_type_macro_f1"] == 1.0

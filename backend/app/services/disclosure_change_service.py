from __future__ import annotations

from app.ai.semantic_change import ChangeClassificationRequest, ChangeClassifierProvider
from app.core.config import Settings
from app.db.models import DisclosureChange, FilingSection, PassageMatch, PassageUnit, SectionMatch
from app.services.comparison_utils import clamp, deterministic_signals, lexical_similarity


class DisclosureChangeService:
    def __init__(self, settings: Settings, classifier: ChangeClassifierProvider) -> None:
        self.settings = settings
        self.classifier = classifier

    async def detect_change(
        self,
        *,
        comparison_id,
        section_match: SectionMatch,
        passage_match: PassageMatch,
        current_passage: PassageUnit | None,
        previous_passage: PassageUnit | None,
        current_section: FilingSection | None,
        previous_section: FilingSection | None,
    ) -> DisclosureChange | None:
        previous_text = previous_passage.text if previous_passage else None
        current_text = current_passage.text if current_passage else None
        signals = deterministic_signals(previous_text, current_text)
        metadata = _section_metadata(current_section, previous_section)
        result = await self.classifier.classify(
            ChangeClassificationRequest(
                previous_text=previous_text,
                current_text=current_text,
                deterministic_signals=signals,
                section_metadata=metadata,
                allowed_labels=[
                    "added",
                    "removed",
                    "strengthened",
                    "weakened",
                    "no_material_change",
                ],
            )
        )
        components = build_materiality_components(
            self.settings,
            result.change_type,
            result.risk_category,
            signals,
            current_section or previous_section,
            previous_text,
            current_text,
            result.confidence,
        )
        evidence = evidence_payload(
            current_passage=current_passage,
            previous_passage=previous_passage,
            current_section=current_section,
            previous_section=previous_section,
        )
        validate_evidence(result.change_type, evidence)
        return DisclosureChange(
            comparison_id=comparison_id,
            section_match_id=section_match.id,
            passage_match_id=passage_match.id,
            change_type=result.change_type,
            risk_category=result.risk_category,
            previous_text=previous_text,
            current_text=current_text,
            changed_spans=result.changed_spans,
            change_summary=result.summary,
            change_explanation=result.explanation,
            materiality_score=float(components["materiality_score"]),
            confidence=result.confidence,
            detection_method="hybrid",
            supporting_evidence=evidence,
            materiality_components=components,
            original_model_output=result.model_dump(),
            model_name=self.classifier.model_name,
            model_version=self.classifier.model_version,
            prompt_version=self.classifier.prompt_version,
        )


def build_materiality_components(
    settings: Settings,
    change_type: str,
    risk_category: str,
    signals: dict[str, object],
    section: FilingSection | None,
    previous_text: str | None,
    current_text: str | None,
    confidence: float,
) -> dict[str, float]:
    novelty = (
        1.0
        if change_type in {"added", "removed"}
        else 1.0 - lexical_similarity(previous_text or "", current_text or "")
    )
    risk_weight = {
        "liquidity": 0.85,
        "revenue_guidance": 0.75,
        "litigation": 0.8,
        "other": 0.35,
    }[risk_category]
    uncertainty = (
        1.0
        if any(
            signals.get(key)
            for key in ("uncertainty_added", "conditional_added", "negation_added")
        )
        else 0.25
    )
    section_importance = (
        0.85
        if section and section.canonical_section_type in {"mda", "risk_factors"}
        else 0.5
    )
    numeric = 1.0 if signals.get("numeric_changed") else 0.0
    score = clamp(
        settings.materiality_weight_novelty * novelty
        + settings.materiality_weight_risk * risk_weight
        + settings.materiality_weight_uncertainty * uncertainty
        + settings.materiality_weight_section * section_importance
        + settings.materiality_weight_numeric * numeric
    )
    return {
        "novelty": round(novelty, 4),
        "risk_weight": risk_weight,
        "uncertainty_shift": uncertainty,
        "section_importance": section_importance,
        "numeric_change": numeric,
        "model_confidence": confidence,
        "materiality_score": score,
    }


def evidence_payload(
    *,
    current_passage: PassageUnit | None,
    previous_passage: PassageUnit | None,
    current_section: FilingSection | None,
    previous_section: FilingSection | None,
) -> dict[str, object]:
    return {
        "previous": _evidence(previous_passage, previous_section),
        "current": _evidence(current_passage, current_section),
    }


def validate_evidence(change_type: str, evidence: dict[str, object]) -> None:
    previous = evidence.get("previous")
    current = evidence.get("current")
    if change_type == "added" and current is None:
        raise ValueError("Added findings require current evidence.")
    if change_type == "removed" and previous is None:
        raise ValueError("Removed findings require previous evidence.")
    if change_type not in {"added", "removed"} and (previous is None or current is None):
        raise ValueError("Matched findings require previous and current evidence.")


def _evidence(
    passage: PassageUnit | None,
    section: FilingSection | None,
) -> dict[str, object] | None:
    if passage is None or section is None:
        return None
    return {
        "filing_id": str(section.filing_id),
        "section_id": str(section.id),
        "passage_id": str(passage.id),
        "part_number": section.part_number,
        "item_number": section.item_number,
        "source_anchor": passage.source_anchor,
        "raw_char_start": passage.raw_char_start,
        "raw_char_end": passage.raw_char_end,
        "content_hash": passage.content_hash,
    }


def _section_metadata(
    current_section: FilingSection | None,
    previous_section: FilingSection | None,
) -> dict[str, object]:
    section = current_section or previous_section
    if section is None:
        return {}
    return {
        "section_type": section.section_type,
        "canonical_section_type": section.canonical_section_type,
        "part_number": section.part_number,
        "item_number": section.item_number,
        "section_title": section.section_title,
    }

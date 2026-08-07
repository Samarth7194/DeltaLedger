from __future__ import annotations

from dataclasses import dataclass

from app.ai.embeddings import EmbeddingService
from app.ai.reranker import RerankerProvider
from app.core.config import Settings
from app.db.models import FilingSection, SectionMatch
from app.services.comparison_utils import clamp, cosine_similarity, lexical_similarity


@dataclass(frozen=True)
class SectionCandidateScore:
    current: FilingSection
    previous: FilingSection
    structural_score: float
    heading_similarity: float
    dense_similarity: float
    lexical_similarity: float
    reranker_score: float
    position_similarity: float
    combined_score: float


class SectionMatchingService:
    def __init__(
        self,
        settings: Settings,
        embeddings: EmbeddingService,
        reranker: RerankerProvider | None,
    ) -> None:
        self.settings = settings
        self.embeddings = embeddings
        self.reranker = reranker

    async def match_sections(
        self,
        *,
        comparison_id,
        current_sections: list[FilingSection],
        previous_sections: list[FilingSection],
    ) -> list[SectionMatch]:
        scores = await self._score_candidates(current_sections, previous_sections)
        used_previous = set()
        matches: list[SectionMatch] = []
        for current in current_sections:
            candidates = [
                score
                for score in scores
                if score.current.id == current.id and score.previous.id not in used_previous
            ]
            best = max(candidates, key=lambda score: score.combined_score, default=None)
            if best is None or best.combined_score < self.settings.section_match_min_score:
                matches.append(self._unmatched_current(comparison_id, current))
                continue
            used_previous.add(best.previous.id)
            matches.append(self._matched(comparison_id, best))

        for previous in previous_sections:
            if previous.id not in used_previous:
                matches.append(self._unmatched_previous(comparison_id, previous))
        return matches

    async def _score_candidates(
        self,
        current_sections: list[FilingSection],
        previous_sections: list[FilingSection],
    ) -> list[SectionCandidateScore]:
        current_texts = [_section_text(section) for section in current_sections]
        previous_texts = [_section_text(section) for section in previous_sections]
        current_vectors = (
            await self.embeddings.embed_documents(current_texts) if current_texts else []
        )
        previous_vectors = (
            await self.embeddings.embed_documents(previous_texts) if previous_texts else []
        )
        scores: list[SectionCandidateScore] = []
        total_current = max(1, len(current_sections) - 1)
        total_previous = max(1, len(previous_sections) - 1)
        for current_index, current in enumerate(current_sections):
            for previous_index, previous in enumerate(previous_sections):
                structural = structural_similarity(current, previous)
                heading = lexical_similarity(current.section_title, previous.section_title)
                lexical = lexical_similarity(_section_text(current), _section_text(previous))
                dense = (
                    cosine_similarity(
                        current_vectors[current_index],
                        previous_vectors[previous_index],
                    )
                    + 1
                ) / 2
                reranker_score = lexical
                if self.reranker is not None:
                    reranked = await self.reranker.rerank(
                        current.section_title,
                        [previous.section_title],
                        top_k=1,
                    )
                    reranker_score = reranked[0].score if reranked else lexical
                position = 1.0 - abs(
                    (current_index / total_current) - (previous_index / total_previous)
                )
                combined = weighted_section_score(
                    self.settings,
                    structural,
                    heading,
                    dense,
                    lexical,
                    reranker_score,
                    position,
                )
                scores.append(
                    SectionCandidateScore(
                        current=current,
                        previous=previous,
                        structural_score=structural,
                        heading_similarity=heading,
                        dense_similarity=round(dense, 4),
                        lexical_similarity=lexical,
                        reranker_score=round(reranker_score, 4),
                        position_similarity=round(position, 4),
                        combined_score=combined,
                    )
                )
        return scores

    def _matched(self, comparison_id, score: SectionCandidateScore) -> SectionMatch:
        if score.structural_score >= 0.98:
            match_type = "exact_structural"
        elif score.structural_score >= 0.5 and score.combined_score >= 0.75:
            match_type = "hybrid"
        else:
            match_type = "semantic"
        return SectionMatch(
            comparison_id=comparison_id,
            current_section_id=score.current.id,
            previous_section_id=score.previous.id,
            match_type=match_type,
            heading_similarity=score.heading_similarity,
            dense_similarity=score.dense_similarity,
            lexical_similarity=score.lexical_similarity,
            reranker_score=score.reranker_score,
            structural_score=score.structural_score,
            combined_score=score.combined_score,
            confidence=score.combined_score,
            match_reason={
                "position_similarity": score.position_similarity,
                "current_title": score.current.section_title,
                "previous_title": score.previous.section_title,
            },
        )

    def _unmatched_current(self, comparison_id, section: FilingSection) -> SectionMatch:
        return SectionMatch(
            comparison_id=comparison_id,
            current_section_id=section.id,
            previous_section_id=None,
            match_type="unmatched_current",
            combined_score=0.0,
            confidence=1.0,
            match_reason={"reason": "no candidate exceeded threshold"},
        )

    def _unmatched_previous(self, comparison_id, section: FilingSection) -> SectionMatch:
        return SectionMatch(
            comparison_id=comparison_id,
            current_section_id=None,
            previous_section_id=section.id,
            match_type="unmatched_previous",
            combined_score=0.0,
            confidence=1.0,
            match_reason={"reason": "section absent from current filing"},
        )


def structural_similarity(current: FilingSection, previous: FilingSection) -> float:
    same_part = current.part_number and current.part_number == previous.part_number
    same_item = current.item_number and current.item_number == previous.item_number
    same_type = current.canonical_section_type == previous.canonical_section_type
    if same_part and same_item and same_type:
        return 1.0
    if same_item and same_type:
        return 0.85
    if same_type:
        return 0.65
    if same_part and same_item:
        return 0.45
    return 0.0


def weighted_section_score(
    settings: Settings,
    structural: float,
    heading: float,
    dense: float,
    lexical: float,
    reranker: float,
    position: float,
) -> float:
    return clamp(
        (settings.section_match_weight_structural * structural)
        + (settings.section_match_weight_heading * heading)
        + (settings.section_match_weight_dense * dense)
        + (settings.section_match_weight_lexical * lexical)
        + (settings.section_match_weight_reranker * reranker)
        + (settings.section_match_weight_position * position)
    )


def _section_text(section: FilingSection) -> str:
    return (
        f"{section.part_number or ''} {section.item_number or ''} "
        f"{section.section_title} {section.normalized_text[:2000]}"
    )

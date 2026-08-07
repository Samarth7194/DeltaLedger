from __future__ import annotations

from dataclasses import dataclass

from app.ai.embeddings import EmbeddingService
from app.ai.reranker import RerankerProvider
from app.core.config import Settings
from app.db.models import PassageMatch, PassageUnit
from app.services.comparison_utils import clamp, cosine_similarity, lexical_similarity


@dataclass(frozen=True)
class PassageScore:
    current: PassageUnit
    previous: PassageUnit
    dense_similarity: float
    lexical_similarity: float
    reranker_score: float
    position_similarity: float
    combined_score: float


class PassageAlignmentService:
    def __init__(
        self,
        settings: Settings,
        embeddings: EmbeddingService,
        reranker: RerankerProvider | None,
    ) -> None:
        self.settings = settings
        self.embeddings = embeddings
        self.reranker = reranker

    async def align_passages(
        self,
        *,
        section_match_id,
        current_passages: list[PassageUnit],
        previous_passages: list[PassageUnit],
    ) -> list[PassageMatch]:
        score_map = await self._score_map(current_passages, previous_passages)
        aligned_pairs = self._monotonic_pairs(current_passages, previous_passages, score_map)
        matches: list[PassageMatch] = []
        for current, previous in aligned_pairs:
            if current is not None and previous is not None:
                score = score_map[(current.id, previous.id)]
                matches.append(
                    PassageMatch(
                        section_match_id=section_match_id,
                        current_passage_id=current.id,
                        previous_passage_id=previous.id,
                        alignment_type="matched",
                        dense_similarity=score.dense_similarity,
                        lexical_similarity=score.lexical_similarity,
                        reranker_score=score.reranker_score,
                        sequence_score=score.position_similarity,
                        combined_score=score.combined_score,
                        confidence=score.combined_score,
                        alignment_metadata={"strategy": "monotonic_dynamic_programming"},
                    )
                )
            elif current is not None:
                matches.append(
                    PassageMatch(
                        section_match_id=section_match_id,
                        current_passage_id=current.id,
                        previous_passage_id=None,
                        alignment_type="added",
                        confidence=1.0,
                        alignment_metadata={"strategy": "monotonic_dynamic_programming"},
                    )
                )
            elif previous is not None:
                matches.append(
                    PassageMatch(
                        section_match_id=section_match_id,
                        current_passage_id=None,
                        previous_passage_id=previous.id,
                        alignment_type="removed",
                        confidence=1.0,
                        alignment_metadata={"strategy": "monotonic_dynamic_programming"},
                    )
                )
        return matches

    async def _score_map(
        self,
        current_passages: list[PassageUnit],
        previous_passages: list[PassageUnit],
    ) -> dict[tuple[object, object], PassageScore]:
        current_vectors = (
            await self.embeddings.embed_documents(
                [passage.normalized_text for passage in current_passages]
            )
            if current_passages
            else []
        )
        previous_vectors = (
            await self.embeddings.embed_documents(
                [passage.normalized_text for passage in previous_passages]
            )
            if previous_passages
            else []
        )
        total_current = max(1, len(current_passages) - 1)
        total_previous = max(1, len(previous_passages) - 1)
        scores: dict[tuple[object, object], PassageScore] = {}
        for current_index, current in enumerate(current_passages):
            for previous_index, previous in enumerate(previous_passages):
                dense = (
                    cosine_similarity(
                        current_vectors[current_index],
                        previous_vectors[previous_index],
                    )
                    + 1
                ) / 2
                lexical = lexical_similarity(current.normalized_text, previous.normalized_text)
                reranker_score = lexical
                if self.reranker is not None:
                    reranked = await self.reranker.rerank(
                        current.normalized_text,
                        [previous.normalized_text],
                        top_k=1,
                    )
                    reranker_score = reranked[0].score if reranked else lexical
                position = 1.0 - abs(
                    (current_index / total_current) - (previous_index / total_previous)
                )
                combined = clamp(
                    (self.settings.passage_alignment_weight_dense * dense)
                    + (self.settings.passage_alignment_weight_lexical * lexical)
                    + (self.settings.passage_alignment_weight_reranker * reranker_score)
                    + (self.settings.passage_alignment_weight_position * position)
                )
                scores[(current.id, previous.id)] = PassageScore(
                    current=current,
                    previous=previous,
                    dense_similarity=round(dense, 4),
                    lexical_similarity=lexical,
                    reranker_score=round(reranker_score, 4),
                    position_similarity=round(position, 4),
                    combined_score=combined,
                )
        return scores

    def _monotonic_pairs(
        self,
        current_passages: list[PassageUnit],
        previous_passages: list[PassageUnit],
        score_map: dict[tuple[object, object], PassageScore],
    ) -> list[tuple[PassageUnit | None, PassageUnit | None]]:
        rows = len(previous_passages)
        cols = len(current_passages)
        dp = [[0.0 for _ in range(cols + 1)] for _ in range(rows + 1)]
        move = [["" for _ in range(cols + 1)] for _ in range(rows + 1)]
        gap = -0.08
        for row in range(1, rows + 1):
            dp[row][0] = dp[row - 1][0] + gap
            move[row][0] = "removed"
        for col in range(1, cols + 1):
            dp[0][col] = dp[0][col - 1] + gap
            move[0][col] = "added"
        for row in range(1, rows + 1):
            previous = previous_passages[row - 1]
            for col in range(1, cols + 1):
                current = current_passages[col - 1]
                score = score_map[(current.id, previous.id)].combined_score
                match_value = dp[row - 1][col - 1] + (
                    score if score >= self.settings.passage_alignment_min_score else -0.12
                )
                removed_value = dp[row - 1][col] + gap
                added_value = dp[row][col - 1] + gap
                best = max(match_value, removed_value, added_value)
                dp[row][col] = best
                move[row][col] = (
                    "matched"
                    if best == match_value and score >= self.settings.passage_alignment_min_score
                    else "removed"
                    if best == removed_value
                    else "added"
                )
        pairs: list[tuple[PassageUnit | None, PassageUnit | None]] = []
        row = rows
        col = cols
        while row > 0 or col > 0:
            direction = move[row][col]
            if direction == "matched":
                pairs.append((current_passages[col - 1], previous_passages[row - 1]))
                row -= 1
                col -= 1
            elif direction == "removed":
                pairs.append((None, previous_passages[row - 1]))
                row -= 1
            else:
                pairs.append((current_passages[col - 1], None))
                col -= 1
        pairs.reverse()
        return pairs

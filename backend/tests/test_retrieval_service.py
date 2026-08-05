from __future__ import annotations

import uuid

from app.repositories.chunk_repository import RetrievalChunkResult
from app.services.retrieval_service import reciprocal_rank_fusion


def _result(chunk_id: uuid.UUID, score: float, text: str = "text") -> RetrievalChunkResult:
    return RetrievalChunkResult(
        chunk_id=chunk_id,
        filing_id=uuid.uuid4(),
        section_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        text=text,
        score=score,
        source_metadata={"section_type": "mda"},
    )


def test_reciprocal_rank_fusion_deduplicates_and_preserves_scores() -> None:
    shared = uuid.uuid4()
    dense_only = uuid.uuid4()
    lexical_only = uuid.uuid4()

    fused = reciprocal_rank_fusion(
        [_result(shared, 0.9), _result(dense_only, 0.8)],
        [_result(lexical_only, 0.7), _result(shared, 0.6)],
    )

    by_id = {result.chunk_id: result for result in fused}
    assert len(fused) == 3
    assert by_id[shared].dense_score == 0.9
    assert by_id[shared].lexical_score == 0.6
    assert fused[0].chunk_id == shared


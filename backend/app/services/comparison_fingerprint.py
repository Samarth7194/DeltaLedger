"""Fingerprint of everything that determines a comparison's section matches and
passage alignments.

Section matching and passage alignment are local (BGE) and slow, and they are a
pure function of: the two filings' parsed sections and chunk embeddings, the
embedding/reranker models, and the matching configuration. When none of those
changed, a resumed run can reuse the persisted matches instead of recomputing
them; when any of them changed, the fingerprint changes and nothing stale is
reused.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.ai.batching import canonical_hash
from app.core.config import Settings

# Settings that change match/alignment output. Deliberately excludes secrets
# and settings that only affect speed (batch sizes, timeouts, device).
_MATCHING_SETTINGS = (
    "passage_segmentation_version",
    "embedding_provider",
    "embedding_model",
    "embedding_dimension",
    "embedding_normalize",
    "embedding_query_instruction",
    "reranker_enabled",
    "reranker_provider",
    "reranker_model",
    "section_match_min_score",
    "section_match_weight_dense",
    "section_match_weight_heading",
    "section_match_weight_lexical",
    "section_match_weight_position",
    "section_match_weight_reranker",
    "section_match_weight_structural",
    "passage_alignment_min_score",
    "passage_alignment_weight_dense",
    "passage_alignment_weight_lexical",
    "passage_alignment_weight_position",
    "passage_alignment_weight_reranker",
)
# Bump when the matching/alignment algorithm itself changes in a way the
# settings above do not capture.
MATCHING_ALGORITHM_VERSION = "matching-reuse-v1"


def matching_fingerprint(
    *,
    settings: Settings,
    comparison: Any,
    embedding_model_name: str | None,
    embedding_model_version: str | None,
    current_sections: Sequence[Any],
    previous_sections: Sequence[Any],
) -> str:
    return canonical_hash(
        {
            "algorithm": MATCHING_ALGORITHM_VERSION,
            "comparison_version": getattr(comparison, "comparison_version", None),
            "current_filing_id": str(getattr(comparison, "current_filing_id", "")),
            "comparison_filing_id": str(getattr(comparison, "comparison_filing_id", "")),
            "embedding_model": [embedding_model_name, embedding_model_version],
            "settings": {name: getattr(settings, name, None) for name in _MATCHING_SETTINGS},
            "current_sections": [_section_fingerprint(s) for s in _ordered(current_sections)],
            "previous_sections": [_section_fingerprint(s) for s in _ordered(previous_sections)],
        }
    )


def _ordered(sections: Sequence[Any]) -> list[Any]:
    return sorted(sections, key=lambda s: (getattr(s, "section_order", 0) or 0, str(s.id)))


def _section_fingerprint(section: Any) -> dict[str, object]:
    chunks = getattr(section, "chunks", None) or []
    return {
        "id": str(section.id),
        "order": getattr(section, "section_order", None),
        "type": getattr(section, "canonical_section_type", None)
        or getattr(section, "section_type", None),
        "title": getattr(section, "section_title", None),
        "text_hash": getattr(section, "text_hash", None),
        # The embeddings section matching reads: which chunks, what content,
        # produced by which embedding model.
        "chunks": [
            [
                str(chunk.id),
                getattr(chunk, "content_hash", None),
                getattr(chunk, "embedding_model", None),
                getattr(chunk, "embedding_version", None),
            ]
            for chunk in sorted(chunks, key=lambda c: getattr(c, "chunk_index", 0) or 0)
        ],
    }

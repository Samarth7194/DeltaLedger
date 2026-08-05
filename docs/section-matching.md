# Section Matching

## Objective

Section matching compares equivalent filing sections across two 10-Q periods for the same company. It must not rely on an LLM as the only matching mechanism.

Phase 2 stores parser evidence needed by later section matching: part number, item
number, canonical section type, source anchor, native element ID, DOM path fallback,
offsets, and section hashes.

## Signals

- Normalized section names.
- SEC filing structure and hierarchy.
- Section type/category.
- Section order and relative position.
- Dense similarity.
- Lexical similarity.
- Cross-encoder reranker score.
- Rule-based matches for standard 10-Q sections.

## Output

Each match records:

- Current section ID.
- Comparison section ID.
- Semantic similarity.
- Lexical similarity.
- Reranker score.
- Combined confidence.
- Match method.
- Reasoning summary.
- Reviewer status.

## Review Path

Low-confidence or conflicting matches remain inspectable. Reviewers can accept or reject matches before downstream disclosure changes are finalized.

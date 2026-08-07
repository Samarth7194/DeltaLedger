# Section Matching

## Objective

Section matching compares equivalent filing sections across two 10-Q periods for the same company. It must not rely on an LLM as the only matching mechanism.

Phase 2 stores parser evidence needed by later section matching: part number, item
number, canonical section type, source anchor, native element ID, DOM path fallback,
offsets, and section hashes.

## Signals

- Structural metadata: part number, item number, and canonical section type.
- Normalized headings.
- Dense embedding similarity over heading plus section text.
- Lexical similarity over normalized section text.
- Optional reranker score.
- Relative section position.

The Phase 3 default weighted score is:

- Structural: `0.30`
- Heading: `0.20`
- Dense: `0.20`
- Lexical: `0.15`
- Reranker: `0.10`
- Position: `0.05`

The default minimum combined score is `0.62`. Candidates below threshold are
stored as `unmatched_current` or `unmatched_previous`. This means section
matching never relies on embeddings alone.

## Output

Each match records:

- Current section ID.
- Comparison section ID.
- Heading similarity.
- Dense similarity.
- Lexical similarity.
- Reranker score.
- Structural score.
- Combined confidence.
- Match type: `exact_structural`, `hybrid`, `semantic`, `unmatched_current`, or
  `unmatched_previous`.
- Match reason metadata.
- Reviewer status.

## Review Path

Low-confidence or conflicting matches remain inspectable. Reviewers can accept or reject matches before downstream disclosure changes are finalized.

## Current Limits

Phase 3 emits one-to-one matches plus explicit unmatched sections. Split and
merged section detection is represented in downstream enums for future support
but is not yet inferred automatically.

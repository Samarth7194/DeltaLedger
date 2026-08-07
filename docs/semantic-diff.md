# Semantic Disclosure Diff

## Scope

Phase 3 compares two parsed 10-Q filings for the same company and detects
reviewable narrative disclosure changes. It does not perform XBRL claim
verification, contradiction detection, or report generation.

## Pipeline

1. Validate the filing pair: same company, distinct filings, 10-Q only, current
   period later than comparison period, parsed sections and chunks present.
2. Create or reuse a versioned `filing_comparisons` row.
3. Segment comparable sections into deterministic paragraph `passage_units`.
4. Match sections using structure, headings, dense similarity, lexical
   similarity, optional reranking, and position.
5. Align passages with monotonic dynamic programming.
6. Detect disclosure changes from each passage match.
7. Store findings with evidence, materiality components, model metadata, and
   review state.

## Passage Alignment

Alignment emits:

- `matched`: current and previous passages align above threshold.
- `added`: a current passage has no previous counterpart.
- `removed`: a previous passage has no current counterpart.

`split` and `merged` are reserved alignment types, but Phase 3 does not infer
them automatically yet.

## Change Classification

The classifier receives typed inputs only:

- previous passage text
- current passage text
- deterministic signals
- section metadata
- allowed labels

It returns:

- `change_type`: `added`, `removed`, `strengthened`, `weakened`, or
  `no_material_change`
- `risk_category`: `liquidity`, `revenue_guidance`, `litigation`, or `other`
- summary, explanation, changed spans, confidence, and materiality reason

The default CI-safe provider is deterministic and offline. Hosted or local model
providers can be added behind the same typed interface.

## Materiality

Materiality is computed from interpretable components:

- novelty
- risk category weight
- uncertainty or conditional-language shift
- section importance
- numeric change

Model confidence is stored separately and is not itself the materiality score.

## Evidence And Review

Each disclosure change stores both current and previous evidence when available:
filing ID, section ID, passage ID, offsets, anchors, and content hashes.

Human review can approve, reject, mark uncertain, or edit a finding. Edited
fields are preserved in `reviewer_edits`; the raw classifier payload remains in
`original_model_output`.

# Contradiction Intelligence

Phase 5 identifies evidence-backed review candidates that may indicate tension
between narrative disclosures, deterministic XBRL verification, and related
cross-section evidence. The system must not accuse a company of fraud,
deception, lying, manipulation, or misconduct. Approved wording includes
potential inconsistency, possible contradiction, magnitude may be overstated,
unsupported by available evidence, and requires analyst review.

## Supported Candidate Types

- `direction_contradiction`
- `magnitude_overstatement`
- `magnitude_understatement`
- `unsupported_qualitative_claim`
- `narrative_cross_section_inconsistency`
- `temporal_narrative_inconsistency`
- `numerical_claim_contradiction`

These are separate from Phase 4 `verification_status`, finding `severity`, and
finding `confidence`.

## Rule-First Pipeline

Phase 5 starts with deterministic and rule-based detectors:

- `RULE_NUMERIC_DIRECTION_MISMATCH`
- `RULE_NUMERIC_REPORTED_CHANGE_MISMATCH`
- `RULE_QUALIFIER_SIGNIFICANT_LOW_CHANGE`
- `RULE_SLIGHT_LARGE_MOVEMENT`
- `RULE_STRONG_LIQUIDITY_MIXED_EVIDENCE`
- `RULE_TEMPORAL_EXPECTATION_CONFLICT`
- `RULE_CROSS_SECTION_POLARITY_CONFLICT`

Magnitude thresholds come from versioned metric policies. Defaults distinguish
percent-change metrics from percentage-point metrics such as gross margin.
These thresholds are review-routing heuristics, not universal financial
materiality rules.

## Evidence Requirements

Every candidate must have at least one primary evidence record in
`contradiction_evidence`.

Numerical candidates require:

- a source narrative claim
- a financial claim record
- a claim verification record
- a selected current XBRL fact
- a selected comparison XBRL fact when a change calculation depends on one
- a reproducible formula and calculation output

If required evidence is missing, the finding status is
`insufficient_evidence`.

Cross-section candidates require:

- two filing section sources
- related topic evidence
- polarity or direction signals
- normalized evidence rows for both statements

## Severity And Confidence

Severity is interpretable review priority. It considers contradiction type,
deterministic evidence strength, measured magnitude, and evidence completeness.
`critical` is intentionally rare and requires explicit policy support.

Confidence measures evidence reliability. Inputs include claim extraction
confidence, fact or verification confidence, rule confidence, and semantic
matching confidence where applicable.

## No Model Assistance

Contradiction findings are produced only by the rule-based detectors in
`contradiction_analysis_service.py` (numerical, magnitude, temporal-narrative, and
cross-section narrative). No model is called. An earlier design included an LLM
`ContradictionClassifierProvider`; it was never wired into the analysis and was
removed, together with its `CONTRADICTION_CLASSIFIER_*` settings. Any future
model-assisted classification would have to be evaluated against negative controls
before use, and model-only suspicions would have to stay low-confidence.

## Human Review

Review states are `pending`, `approved`, `rejected`, `edited`, and `uncertain`.
Reviewers may edit type, severity, risk category, summary, and explanation.
The system preserves original findings, rule IDs, evidence rows,
review comments, reviewer identity, timestamps, and reviewer edits.

## API

- `POST /api/v1/comparisons/{comparison_id}/contradictions/analyze`
- `GET /api/v1/comparisons/{comparison_id}/contradictions`
- `GET /api/v1/comparisons/{comparison_id}/contradiction-summary`
- `GET /api/v1/contradictions/{finding_id}`
- `GET /api/v1/contradictions/{finding_id}/evidence`
- `PATCH /api/v1/contradictions/{finding_id}/review`

# Evaluation Methodology

## Dataset

The MVP benchmark dataset must contain at least 150 versioned examples. Ground truth must not be generated exclusively by an LLM. Human review and documented annotation rules are required.

Example categories:

- Correct section matches.
- Incorrect section-match negatives.
- Added disclosures.
- Removed disclosures.
- Strengthened language.
- Weakened language.
- Financial claims.
- Correct XBRL mappings.
- Numerical verification cases.
- Genuine contradictions.
- False contradiction traps.
- Unsupported-claim examples.
- Citation-validation examples.

Each example includes:

- Company, filing periods, source references.
- Expected section match.
- Expected change type and risk category.
- Expected numerical values and calculation.
- Expected contradiction status.
- Human annotations.
- Dataset version.

## Phase 3 Seed Fixture

Phase 3 adds `backend/tests/fixtures/comparison/phase3_examples.json`, a
40-example manually curated seed fixture for semantic disclosure changes. It is
not the full MVP benchmark, but it gives CI and reviewers a stable starting
point for regression checks.

The seed fixture contains:

- 8 added-disclosure examples.
- 8 removed-disclosure examples.
- 8 strengthened-language examples.
- 8 weakened-language examples.
- 8 no-material-change examples.

Each example includes previous text, current text, expected change type,
expected risk category, expected important changed spans, and annotation notes.

Annotation rules:

- `added`: previous passage is absent and current passage introduces a new
  disclosure.
- `removed`: current passage is absent and previous passage contained a
  disclosure.
- `strengthened`: current passage reduces uncertainty, adds commitment, removes
  negative/risk language, or otherwise makes the disclosure materially stronger.
- `weakened`: current passage adds uncertainty, conditions, negation, risk terms,
  or removes commitment.
- `no_material_change`: wording is identical or semantically unchanged for the
  available evidence.
- Risk category is assigned from the dominant topic: liquidity/financing,
  revenue/demand/guidance, litigation/legal proceedings, or other.

## Phase 4 Seed Fixture

Phase 4 adds `backend/tests/fixtures/financial_claims/phase4_examples.json`, a
60-example curated fixture for financial claim extraction and verification. It
is deterministic and CI-safe; it does not call external LLMs, live SEC services,
or hosted model endpoints.

The seed fixture contains:

- 15 absolute-value examples.
- 15 percentage-change examples.
- 10 percentage-point or basis-point examples.
- 10 period-resolution examples.
- 10 ambiguous, unsupported, mismatch, or calculation-error examples.

Coverage includes revenue, gross profit, gross margin, operating income, net
income, cash and cash equivalents, long-term debt, basic EPS, and diluted EPS.

## Metrics

Retrieval:

- Recall@5, Recall@10, Precision@K, MRR, nDCG.

Section matching:

- Accuracy, precision, recall, F1.

Change detection:

- Precision, recall, macro F1, per-class F1.

Risk classification:

- Macro F1 and confusion matrix.

Phase 3 includes deterministic metric helpers in
`app.services.evaluation_metrics` for per-label precision, recall, F1, macro-F1,
and aggregate change-type/risk-category reporting. These helpers do not call
live models.

Phase 4 includes `app.services.financial_evaluation_metrics` for exact-match
accuracy and status-count reporting over labeled verification examples.

Numerical extraction:

- Exact match and tolerance-based accuracy.

XBRL verification:

- Correct concept selection, period selection, unit selection, and calculation accuracy.

Contradiction detection:

- Precision, recall, F1, and false-positive rate.

Citation quality:

- Citation validity, citation precision, and evidence coverage.

Operations:

- p50/p95 latency, processing time per filing, processing time per analysis, token usage, model cost, retry count, successful-run rate.

Human review:

- Approval rate, rejection rate, edit rate, confidence calibration, reviewer agreement.

## Phase 8 Offline Runner

Phase 8 adds `python -m app.cli.evaluate --suite all --offline`. The runner
validates dataset manifests, adapts existing Phase 3/4/5 fixtures, evaluates
compact retrieval and evidence datasets, and writes JSON plus Markdown candidate
reports under `backend/evaluation/reports`.

The runner never fills placeholder scores. If a labelled dataset or prediction
artifact is missing, it returns `not_evaluated` or `no_data` with a reason.

See [evaluation-suite.md](evaluation-suite.md),
[quality-gates.md](quality-gates.md), and
[confidence-calibration.md](confidence-calibration.md).

## CI Gates

The build should fail when:

- Retrieval Recall@10 falls below threshold.
- Section-match F1 regresses beyond tolerance.
- Citation precision falls below threshold.
- Numerical verification accuracy regresses.
- Contradiction false positives exceed threshold.
- API tests fail.
- Database migrations fail.
- Security tests fail.

Initial thresholds should be conservative until the human-labeled dataset is mature. Threshold changes require a documented reason and dataset version reference. Phase 8 makes deterministic safety checks hard gates and leaves semantic metrics as reporting-only unless an approved baseline is supplied.

## Evaluation Artifacts

Each run generates:

- Dataset version.
- Git commit when available.
- Model and prompt versions.
- Metric table.
- Threshold pass/fail decisions.
- Failed example IDs.
- Retrieval traces for failed retrieval and section-matching examples.
- Citation validation failures.
- Contradiction false-positive examples.

## RAGAS Usage

RAGAS can evaluate retrieval and answer faithfulness where report prose is generated from evidence. Custom deterministic evaluators remain authoritative for section matching, XBRL verification, calculations, and citation existence checks.

## Portfolio Presentation

Evaluation results should be described as development benchmark results unless
they come from a broader approved validation program. Always show dataset name,
dataset version, sample count, annotation provenance, candidate/baseline status,
and metrics that could not be evaluated.

Do not cherry-pick only favorable metrics. Present
`evidence_backed_finding_rate` and `unsupported_finding_rate` together because
they describe evidence grounding from opposite directions. Avoid production
accuracy claims until CI, infrastructure jobs, and approved baselines validate
the same release.

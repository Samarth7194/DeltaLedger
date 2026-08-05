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

## Metrics

Retrieval:

- Recall@5, Recall@10, Precision@K, MRR, nDCG.

Section matching:

- Accuracy, precision, recall, F1.

Change detection:

- Precision, recall, macro F1, per-class F1.

Risk classification:

- Macro F1 and confusion matrix.

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

Initial thresholds should be conservative until the human-labeled dataset is mature. Threshold changes require a documented reason and dataset version reference.

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


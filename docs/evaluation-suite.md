# Evaluation Suite

Phase 8 adds an offline, deterministic evaluation layer for measuring
DeltaLedger quality without live SEC calls or hosted model credentials.

## Layout

- `backend/evaluation/datasets`: versioned dataset manifests and compact
  offline benchmark examples.
- `backend/app/evaluation`: dataset loaders, metric functions, evaluators,
  report generation, baseline comparison, and quality gates.
- `backend/evaluation/reports`: generated candidate JSON and Markdown reports.
- `backend/evaluation/baselines`: placeholder location for approved baselines.

Existing curated fixtures are reused through adapters:

- Phase 3: `backend/tests/fixtures/comparison/phase3_examples.json`
- Phase 4: `backend/tests/fixtures/financial_claims/phase4_examples.json`
- Phase 5: `backend/tests/fixtures/contradictions/phase5_examples.json`

The adapters preserve those examples instead of duplicating them into benchmark
data files.

## Command

```powershell
Set-Location backend
python -m app.cli.evaluate --suite all --offline --output-dir evaluation/reports
```

The runner writes:

- `evaluation/reports/phase8_candidate_report.json`
- `evaluation/reports/phase8_candidate_report.md`

The generated files are candidate artifacts. They are not approved baselines
until reviewed and explicitly committed as such.

## Metric Reporting Rule

Metrics are emitted only when all of the following are true:

- labelled data exists
- an evaluator produced predictions or measurements
- the denominator is non-zero
- methodology is documented

Otherwise the metric value is `not_evaluated` or `no_data` with a reason.

## Offline Suites

- Retrieval: Recall@K, Precision@K, MRR, nDCG, hit rate, and ablation tables for
  dense, lexical, hybrid, and hybrid plus reranker ranking outputs.
- Phase 3: disclosure change and risk category classification using the
  deterministic Phase 3 classifier.
- Phase 4: labelled verification fixture preservation plus number
  normalization evaluation.
- Phase 5: contradiction type metrics using deterministic structured-evidence
  rules where the fixture supports them.
- Evidence: citation resolution, source hash validity, calculation evidence,
  evidence-backed finding rate, and unsupported finding rate.
- Human review and workflow operations: return `no_data` until a labelled review
  or operational benchmark dataset exists.

## Real-Model Evaluation

Real-model evaluation is intentionally not run by default. Any model-provider
benchmark should be a manual workflow with secrets protected by GitHub Actions
and should still emit the same dataset, evaluator, code version, and report
metadata.

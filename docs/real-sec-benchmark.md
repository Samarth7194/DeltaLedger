# Real SEC Benchmark

Phase 10A adds `real-sec-v1`, a versioned benchmark foundation for measuring
DeltaLedger on real 10-Q filing pairs without adding live SEC calls to standard
CI.

## Scope

The dataset lives at `backend/evaluation/datasets/real_sec_v1` and contains:

- 12 public companies across technology, retail, financial services,
  healthcare, industrials, energy, telecom/media, transport, and automotive.
- 24 10-Q filing pairs from 2025 and 2026.
- 16 machine-readable annotation records covering section matching, passage
  alignment, disclosure change, financial claims, XBRL resolution, verification,
  contradiction candidates, and evidence quality.
- 7 negative controls for false-positive traps and non-match behavior.

The dataset stores SEC traceability metadata instead of large filing HTML:
ticker, CIK, accession numbers, filing dates, report periods, form type, and
primary document names. Source filing URLs are reconstructable from:

```text
https://www.sec.gov/Archives/edgar/data/{cik_without_leading_zeroes}/{accession_without_hyphens}/{primary_document}
```

## Label Status

All initial labels are `candidate`. Candidate labels are scaffolding for review
and must not be described as gold labels or model-quality proof.

Allowed annotation statuses are:

- `candidate`
- `human_reviewed`
- `approved`
- `rejected`
- `uncertain`

Only `approved` examples are eligible for metric scoring. If a task has no
approved labels, the evaluator reports `not_evaluated` with a reason.

## Human Review Workflow

Run from `backend`:

```powershell
python -m app.cli.real_sec_benchmark validate
python -m app.cli.real_sec_benchmark summary
python -m app.cli.real_sec_benchmark list-pending
python -m app.cli.real_sec_benchmark inspect real-sec-v1-ct-001
```

After a reviewer checks source filing text, selected XBRL facts, evidence, and
the expected label:

```powershell
python -m app.cli.real_sec_benchmark set-status real-sec-v1-ct-001 approved --annotator "reviewer@example.com" --notes "Reviewed source filing passages and accepted negative control."
```

Use `rejected` when source evidence does not support the candidate label. Use
`uncertain` when the label remains ambiguous after review.

## Validation Rules

The validator checks:

- unique filing pair IDs and annotation IDs
- known company references
- 10-Q form type
- current report period after previous report period
- duplicate accession-pair fingerprints
- valid task and annotation-status enums
- valid task-specific expected-label enums
- approved label review metadata
- required negative-control coverage
- company-aware split consistency

## Splits

Splits are company-aware to reduce leakage from issuer-specific wording:

- Development: AAPL, MSFT, AMZN, WMT
- Validation: JPM, UNH, CAT, XOM
- Test: VZ, DAL, TSLA, NFLX

Examples should not be moved across splits without also reviewing near-duplicate
issuer language risk.

## Evaluator Integration

`python -m app.cli.evaluate --suite all --offline` includes the real SEC suite
through the existing Phase 8 evaluator. The suite reports annotation summaries,
per-task metrics for approved examples with predictions, contradiction
false-positive rate where labels support it, and error-analysis rows containing
example ID, company, pair ID, expected label, predicted label, confidence, and
failure category.

Standard CI remains offline and deterministic. Live SEC refresh, primary HTML
capture, or Company Facts expansion must be run as an explicit review workflow
and should not commit large raw HTML artifacts.

# Live Provider Evaluation

- Run: `42f78f1b-8aca-4de3-80ed-0bac6924a1e7`  (code `ad44e1c`)
- Status: **completed**
- Created: 2026-09-29T07:31:25.379796+00:00  Finished: 2026-09-29T07:32:14.721105+00:00
- Provider: `openai_compatible` at `generativelanguage.googleapis.com`  (chat delay 15.0s, client max retries 5, repair attempts 1)
- `claim_extraction`: model `gemini-3.5-flash-lite`, mode `batch`, prompt `financial-claim-extraction-batch-json-v2+44c2dfaf`, dataset `phase4_fixture` `phase4-v1` (author-written fixture (tests/fixtures/financial_claims)), split `held_out`
- Provider chat requests (incl. repair attempts): 4; reported tokens in/out/total: 3186/4271/7457

> **Read this first.** Both datasets are small and were written by the project author, not sampled from filings and not independently labelled. The comparison is between the pipeline's deterministic components and the configured LLM on identical inputs, from a **single run** with no prompt tuning; LLM output is not guaranteed to repeat. Treat the numbers as a first honest measurement, not as a quality claim.

## Financial-claim extraction

Scored 30 of 30 sentences. Provider status: {'ok': 30}.

Systems: **baseline** = the pipeline's deterministic extractor (metric-alias match + number parser) on its own; **Gemini** = the model on every sentence; **hybrid** = what the pipeline actually does (deterministic result if it found anything, else the model). Claim-type gold exists only for the three categories that name a type; `canonical_metric_accuracy` counts an item with no gold metric as correct only when no claim asserts a metric.

| metric | baseline | Gemini | hybrid (pipeline) |
|---|---|---|---|
| canonical_metric_accuracy | 0.867 | 0.933 | 0.900 |
| claim_type_accuracy (typed items) | 0.850 | 1.000 | 0.900 |
| exact match (1 claim, metric + type) | 0.800 | 0.950 | 0.850 |
| claim recall (items with a gold metric) | 0.964 | 1.000 | 1.000 |
| spurious-metric rate (items with no gold metric) | 0.000 | 0.000 | 0.000 |

### Metric accuracy by category

| category | baseline | Gemini | hybrid |
|---|---|---|---|
| absolute_value | 1.000 | 1.000 | 1.000 |
| ambiguous_or_error | 0.800 | 1.000 | 0.800 |
| percentage_change | 0.875 | 1.000 | 1.000 |
| percentage_point_change | 0.600 | 0.800 | 0.600 |
| period_resolution | 1.000 | 0.800 | 1.000 |

### Gemini failure examples

- `pp-004` (percentage_point_change) "Operating margin improved by 75 basis points." expected **operating_income/percentage_point_change**, Gemini **None/percentage_point_change** (ok)
- `period-010` (period_resolution) "Cash increased during the quarter." expected **cash_and_cash_equivalents/None**, Gemini **None/directional_change** (ok)

## Real-SEC approved records

Status: **not_evaluated** - 1 approved financial-claim record(s), 0 with stored input text (of 10 approved records across all tasks). The real-SEC benchmark stores identifiers and locators, not filing text, and only 1 human-approved record(s) are financial-claim records; none stores the passage to extract from. Claim extraction is therefore scored on the author-written Phase 4 fixture instead.

## Phase 4 metrics

| metric | value | n | status |
|---|---|---|---|
| claim_extraction.canonical_metric_accuracy (gemini:gemini-3.5-flash-lite) | 0.933 | 30 | evaluated |
| claim_extraction.claim_type_accuracy (gemini:gemini-3.5-flash-lite) | 1.000 | 20 | evaluated |
| xbrl_resolution.concept_selection_accuracy | not evaluated | 0 | not_evaluated |
| xbrl_resolution.period_resolution_accuracy | not evaluated | 0 | not_evaluated |
| xbrl_resolution.unit_selection_accuracy | not evaluated | 0 | not_evaluated |
| verification_status | not evaluated | 0 | not_evaluated |
| unsafe_period_match_rate | not evaluated | 0 | not_evaluated |
| unsafe_unit_acceptance_rate | not evaluated | 0 | not_evaluated |
| deterministic_calculation.reproducible_calculation_rate | not evaluated | 0 | not_evaluated |

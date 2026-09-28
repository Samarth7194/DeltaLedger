# Live Provider Evaluation

- Run: `bfce6fae-365c-4c9f-8722-1a96e65d778c`  (code `51d8e0e`)
- Status: **completed**
- Created: 2026-09-28T19:08:52.608316+00:00  Finished: 2026-09-28T20:00:17.583692+00:00
- Provider: `openai_compatible` at `generativelanguage.googleapis.com`  (chat delay 15.0s, client max retries 5, repair attempts 1)
- `disclosure_change`: model `gemini-3.5-flash-lite`, mode `batch`, prompt `disclosure-change-batch-json-v1+f9480f37`, dataset `phase3_fixture` `phase3-v1` (author-written fixture (tests/fixtures/comparison))
- `claim_extraction`: model `gemini-3.5-flash-lite`, mode `batch`, prompt `financial-claim-extraction-batch-json-v1+6f0b00a3`, dataset `phase4_fixture` `phase4-v1` (author-written fixture (tests/fixtures/financial_claims))
- Provider chat requests (incl. repair attempts): 92; reported tokens in/out/total: 26545/17056/43601

> **Read this first.** Both datasets are small and were written by the project author, not sampled from filings and not independently labelled. The comparison is between the pipeline's deterministic components and the configured LLM on identical inputs, from a **single run** with no prompt tuning; LLM output is not guaranteed to repeat. Treat the numbers as a first honest measurement, not as a quality claim.

## Disclosure-change classification

Scored 40 of 40 items. Provider status: {'ok': 40}.

| metric | deterministic baseline | Gemini |
|---|---|---|
| change_type accuracy | 0.975 | 1.000 |
| change_type macro F1 | 0.975 | 1.000 |
| change_type weighted F1 | 0.975 | 1.000 |
| risk_category accuracy | 1.000 | 1.000 |
| risk_category macro F1 | 1.000 | 1.000 |

### Per-class (change_type): precision / recall / F1

| class | support | baseline P / R / F1 | Gemini P / R / F1 |
|---|---|---|---|
| added | 8 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| removed | 8 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| strengthened | 8 | 1.000 / 0.875 / 0.933 | 1.000 / 1.000 / 1.000 |
| weakened | 8 | 0.889 / 1.000 / 0.941 | 1.000 / 1.000 / 1.000 |
| no_material_change | 8 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |

### Confusion matrix - Gemini (change_type)

| expected \ predicted | added | removed | strengthened | weakened | no_material_change | <no_prediction> |
|---|---|---|---|---|---|---|
| **added** | 8 | 0 | 0 | 0 | 0 | 0 |
| **removed** | 0 | 8 | 0 | 0 | 0 | 0 |
| **strengthened** | 0 | 0 | 8 | 0 | 0 | 0 |
| **weakened** | 0 | 0 | 0 | 8 | 0 | 0 |
| **no_material_change** | 0 | 0 | 0 | 0 | 8 | 0 |

### Confusion matrix - deterministic baseline (change_type)

| expected \ predicted | added | removed | strengthened | weakened | no_material_change | <no_prediction> |
|---|---|---|---|---|---|---|
| **added** | 8 | 0 | 0 | 0 | 0 | 0 |
| **removed** | 0 | 8 | 0 | 0 | 0 | 0 |
| **strengthened** | 0 | 0 | 7 | 1 | 0 | 0 |
| **weakened** | 0 | 0 | 0 | 8 | 0 | 0 |
| **no_material_change** | 0 | 0 | 0 | 0 | 8 | 0 |

### Gemini failure examples (change_type)

_None._

## Financial-claim extraction

Scored 60 of 60 sentences. Provider status: {'invalid_output': 32, 'ok': 28}.

Systems: **baseline** = the pipeline's deterministic extractor (metric-alias match + number parser) on its own; **Gemini** = the model on every sentence; **hybrid** = what the pipeline actually does (deterministic result if it found anything, else the model). Claim-type gold exists only for the three categories that name a type; `canonical_metric_accuracy` counts an item with no gold metric as correct only when no claim asserts a metric.

| metric | baseline | Gemini | hybrid (pipeline) |
|---|---|---|---|
| canonical_metric_accuracy | 0.917 | 0.067 | 0.917 |
| claim_type_accuracy (typed items) | 0.900 | 0.025 | 0.900 |
| exact match (1 claim, metric + type) | 0.875 | 0.025 | 0.875 |
| claim recall (items with a gold metric) | 0.965 | 0.018 | 0.965 |
| spurious-metric rate (items with no gold metric) | 0.000 | 0.000 | 0.000 |

### Metric accuracy by category

| category | baseline | Gemini | hybrid |
|---|---|---|---|
| absolute_value | 1.000 | 0.000 | 1.000 |
| ambiguous_or_error | 0.900 | 0.300 | 0.900 |
| percentage_change | 0.867 | 0.067 | 0.867 |
| percentage_point_change | 0.800 | 0.000 | 0.800 |
| period_resolution | 1.000 | 0.000 | 1.000 |

### Gemini failure examples

- `abs-001` (absolute_value) "Revenue was $112 million for the quarter." expected **revenue/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-002` (absolute_value) "Net sales totaled $1.25 billion." expected **revenue/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-003` (absolute_value) "Gross profit was $44.8 million." expected **gross_profit/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-004` (absolute_value) "Operating income was $9.4 million." expected **operating_income/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-005` (absolute_value) "Net income was $6.2 million." expected **net_income/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-006` (absolute_value) "Cash and cash equivalents were $300 million at quarter end." expected **cash_and_cash_equivalents/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-007` (absolute_value) "Long-term debt was $800 million." expected **long_term_debt/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-008` (absolute_value) "Basic EPS was $1.20." expected **basic_eps/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-009` (absolute_value) "Diluted EPS was $1.16." expected **diluted_eps/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-010` (absolute_value) "Revenue was $(12 million)." expected **revenue/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-011` (absolute_value) "Gross profit totaled USD 44.8 million." expected **gross_profit/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-012` (absolute_value) "Cash was $0.3 billion." expected **cash_and_cash_equivalents/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-013` (absolute_value) "Borrowings were $800 million." expected **long_term_debt/absolute_value**, Gemini **<no_prediction>** (ok)
- `abs-014` (absolute_value) "Earnings per share basic was $1.20 per share." expected **basic_eps/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- `abs-015` (absolute_value) "Revenue was $111 million for the quarter." expected **revenue/absolute_value**, Gemini **<no_prediction>** (invalid_output)
- … and 41 more in the JSON results.

## Real-SEC approved records

Status: **not_evaluated** - 1 approved financial-claim record(s), 0 with stored input text (of 10 approved records across all tasks). The real-SEC benchmark stores identifiers and locators, not filing text, and only 1 human-approved record(s) are financial-claim records; none stores the passage to extract from. Claim extraction is therefore scored on the author-written Phase 4 fixture instead.

## Phase 4 metrics

| metric | value | n | status |
|---|---|---|---|
| claim_extraction.canonical_metric_accuracy (gemini:gemini-3.5-flash-lite) | 0.067 | 60 | evaluated |
| claim_extraction.claim_type_accuracy (gemini:gemini-3.5-flash-lite) | 0.025 | 40 | evaluated |
| xbrl_resolution.concept_selection_accuracy | not evaluated | 0 | not_evaluated |
| xbrl_resolution.period_resolution_accuracy | not evaluated | 0 | not_evaluated |
| xbrl_resolution.unit_selection_accuracy | not evaluated | 0 | not_evaluated |
| verification_status | not evaluated | 0 | not_evaluated |
| unsafe_period_match_rate | not evaluated | 0 | not_evaluated |
| unsafe_unit_acceptance_rate | not evaluated | 0 | not_evaluated |
| deterministic_calculation.reproducible_calculation_rate | not evaluated | 0 | not_evaluated |

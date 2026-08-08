# XBRL Verification

## Principle

All authoritative financial arithmetic is performed by Python, using `Decimal` where appropriate. The LLM may explain deterministic results but cannot calculate the authoritative answer.

## Verification Engine

The engine:

1. Resolves narrative metrics to candidate XBRL concepts using a controlled metric dictionary.
2. Selects the correct reporting period.
3. Selects the correct unit.
4. Avoids duplicate facts.
5. Handles instant and duration facts.
6. Handles year-to-date and quarterly values.
7. Calculates absolute and percentage changes.
8. Records the exact formula.
9. Returns a verification status.

## Statuses

- `verified`
- `approximately_verified`
- `contradicted`
- `insufficient_data`
- `ambiguous_metric`
- `ambiguous_fact`
- `unsupported_metric`
- `period_mismatch`
- `unit_mismatch`
- `accession_mismatch`
- `zero_denominator`
- `calculation_error`

## Fact Ranking

Phase 4 ranks candidates from the existing `xbrl_facts` table; no duplicate XBRL
store is introduced. Candidate scores combine:

- Concept priority from `financial_metric_concepts`.
- Period compatibility and period-end/report-period match.
- Unit compatibility.
- Accession-number match.
- XBRL frame availability.

The top fact is selected only when it clears the minimum score and ambiguity
margin. A wrong-unit or wrong-period candidate cannot be selected even when the
other score components are strong. All candidates are stored so reviewers can see
why a fact was selected or rejected.

## Period Safeguards

Duration facts are classified as quarterly, year-to-date, annual, or other based
on start/end dates and fiscal period. Instant metrics such as cash and debt
require instant facts. Quarterly and year-to-date facts are not interchangeable.

## Derived Metrics

Gross margin is calculated as:

```text
GrossProfit / Revenue * 100
```

The calculation requires same-accession, same-period, compatible monetary input
facts and a non-zero revenue denominator. Missing facts are not treated as zero.

## Metric Alias Examples

- `net sales` -> `revenue`
- `sales` -> `revenue`
- `gross profit percentage` -> `gross_margin`
- `borrowings` -> `long_term_debt`
- `cash and cash equivalents` -> `cash_and_cash_equivalents`

## Stored Evidence

Verification records store inputs, selected XBRL fact IDs, calculations, differences, formula, confidence, and limitations so every result is reproducible.

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
- `period_mismatch`
- `unit_mismatch`

## Metric Alias Examples

- `net sales` -> `revenue`
- `sales` -> `revenue`
- `gross profit percentage` -> `gross_margin`
- `borrowings` -> `debt`
- `cash and cash equivalents` -> `cash`

## Stored Evidence

Verification records store inputs, selected XBRL fact IDs, calculations, differences, formula, confidence, and limitations so every result is reproducible.


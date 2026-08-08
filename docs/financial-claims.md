# Financial Claim Verification

Phase 4 extracts numerical claims from filing text and verifies them against the
existing `xbrl_facts` table. It does not generate contradiction or
misleadingness scores; those remain Phase 5 work.

## Flow

1. Extract candidate claim sentences from filing sections or matched comparison
   evidence.
2. Normalize numbers with `Decimal`, preserving whether a value is monetary,
   percent, percentage points, basis points, per-share, or absolute.
3. Resolve the narrative metric to the seeded canonical metric registry.
4. Rank XBRL fact candidates by concept priority, reporting period, unit,
   accession match, and frame availability.
5. Preserve all candidates in `claim_fact_candidates`; select one only when the
   top candidate passes the configured score and ambiguity thresholds.
6. Calculate verification outputs deterministically and store one versioned
   `claim_verifications` row per claim/version.

## Canonical Metrics

The seeded Phase 4 registry supports:

- `revenue`
- `gross_profit`
- `gross_margin`
- `operating_income`
- `net_income`
- `cash_and_cash_equivalents`
- `long_term_debt`
- `basic_eps`
- `diluted_eps`

`gross_margin` is derived from gross profit and revenue. The verifier does not
invent missing facts and never treats missing values as zero.

## Review

Reviewers can approve, reject, mark uncertain, or edit extracted claim metadata
through the financial-claims API. The original extractor payload remains in
`original_model_output`; previous reviewed values are recorded in
`reviewer_edits`.

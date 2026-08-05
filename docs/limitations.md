# Limitations

## MVP Limits

- Limited to 5 US public companies.
- Limited to 4 quarterly reporting periods per company.
- Limited to 10-Q filings.
- Limited to SEC filing HTML and SEC company facts/XBRL APIs.
- Initial change categories are added, removed, strengthened, and weakened language.
- Initial risk categories are revenue and margin, liquidity and debt, and customer concentration.

## Analytical Limits

- Findings may be incomplete or incorrect.
- Contradiction flags are potential inconsistencies, not allegations.
- Some claims may rely on non-GAAP metrics or table context not available in XBRL company facts.
- SEC filing formats vary and parser quality must be measured with fixtures.
- Human review is required before relying on published findings.

## Responsible Use

DeltaLedger AI does not provide investment advice, buy/sell/hold recommendations, or price predictions. Original SEC filings remain the authoritative source.

## Phase 2.5 Known Limits

- The parser suite includes one full unmodified SEC EDGAR 10-Q fixture plus
  synthetic SEC-style reduced fixtures. More issuers are still needed before
  parser robustness can be claimed broadly.
- Live SEC API tests are intentionally disabled by default and require
  `RUN_LIVE_TESTS=1`.
- Real Hugging Face embedding and reranker smoke tests are intentionally disabled
  by default and require `RUN_MODEL_SMOKE=1`.
- Local PGVector and MinIO tests require Docker Compose services or equivalent
  local or managed services to be running. Docker is not required on the laptop
  when managed PostgreSQL/Redis and filesystem storage are used.
- Parser coverage now includes repeated headings, Item 1A classification, tables,
  not-applicable sections, evidence hashes, and deterministic output, but it does
  not yet prove robust parsing for every issuer-specific SEC HTML variant.
- Phase 3 capabilities are intentionally not implemented here: temporal filing
  comparison, semantic disclosure diff, financial-claim extraction, XBRL
  contradiction detection, and LangGraph analysis.

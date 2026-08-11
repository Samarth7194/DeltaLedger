# Limitations

## MVP Limits

- Limited to 5 US public companies.
- Limited to 4 quarterly reporting periods per company.
- Limited to 10-Q filings.
- Limited to SEC filing HTML and SEC company facts/XBRL APIs.
- Initial change categories are added, removed, strengthened, weakened, and
  no-material-change.
- Initial Phase 3 risk categories are liquidity, revenue guidance, litigation,
  and other.

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
## Phase 3 Known Limits

- Temporal 10-Q comparison, section matching, passage alignment, and semantic
  disclosure-change storage are implemented.
- Passage segmentation is paragraph-based. Sentence, list-item, and table-text
  units are schema-supported but not yet generated.
- Passage alignment emits matched, added, and removed passages. Split and merged
  passage types are reserved but not yet inferred.
- The default classifier is deterministic and CI-safe. It is useful for
  repeatable acceptance tests but should be replaced or augmented before
  claiming production model quality.
- The 40-example Phase 3 fixture is a seed regression set, not the full
  150-example human-labeled benchmark.
- Contradiction detection, LangGraph analysis orchestration, report generation,
  and frontend workflows remain future phases.

## Phase 4 Known Limits

- Financial-claim extraction and XBRL verification are implemented for the
  seeded canonical metrics only.
- The default extractor is deterministic/fake in CI. It is designed for
  repeatable acceptance tests, not broad production-quality language coverage.
- Non-GAAP metrics, adjusted EBITDA, operating margin, and issuer-specific custom
  XBRL concepts are unsupported until added to the registry with tests.
- Gross margin is the only derived metric implemented.
- Fact selection preserves candidates and abstains on ambiguity, unit mismatch,
  or period mismatch. Reviewer fact-mapping selection is supported for preserved
  candidates.
- Phase 4 does not produce contradiction or misleadingness scores. It only
  verifies extracted numerical claims against XBRL facts.

## Phase 7.5 Known Limits

- Playwright E2E uses deterministic mocked FastAPI responses at the HTTP
  boundary. It verifies frontend contract behavior, not a live browser-to-real
  database run.
- Postgres LangGraph checkpoint acceptance is marker-gated and requires a real
  migrated PostgreSQL test database with the checkpoint tables initialized.
- Frontend JSON export is implemented. Server-side PDF generation remains later
  hardening.
- Dependency audit findings are reviewed locally; forced major upgrades are not
  applied during Phase 7.5.

## Phase 8 Known Limits

- Retrieval and evidence datasets are compact offline fixtures, not a full live
  PGVector benchmark.
- The existing Phase 4 fixture preserves expected labels but does not yet store
  offline verifier predictions, so several XBRL-resolution metrics are
  `not_evaluated`.
- The existing Phase 5 fixture does not include true non-contradiction negative
  controls, so false-positive rate is `not_evaluated` for that suite.
- Human-review analytics and workflow operational metrics return `no_data`
  until labelled review and workflow event benchmark datasets exist.
- Generated Phase 8 reports are candidate artifacts; no baseline is approved
  automatically.

## Phase 9 Known Limits

- Phase 9 makes the project deployment-ready but does not perform a remote
  production deployment.
- Production model-provider behavior depends on real provider configuration and
  should be evaluated separately from deterministic CI fakes.
- The deterministic demo dataset is synthetic/reduced-real and designed for
  walkthrough stability, not issuer coverage.
- Evaluation datasets remain small and should not be described as production
  validation across all public companies.
- XBRL issuer extensions, non-GAAP metrics, and table-heavy disclosures can
  still require analyst review or future resolver improvements.
- Potential inconsistency candidates are not misconduct determinations.
- Human-review/resume flows need authentication and authorization before public
  multi-user deployment.
- Current dependency audit results may include unresolved vulnerabilities that
  require deliberate package upgrade decisions.

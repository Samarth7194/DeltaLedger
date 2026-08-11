# API Contract Summary

All APIs are versioned under `/api/v1`. Responses use a consistent envelope:

```json
{
  "data": {},
  "meta": {
    "request_id": "req_...",
    "pagination": null
  },
  "error": null
}
```

Errors use typed codes:

```json
{
  "data": null,
  "meta": {
    "request_id": "req_..."
  },
  "error": {
    "code": "filing_not_found",
    "message": "Filing was not found.",
    "details": {}
  }
}
```

Creation APIs accept `Idempotency-Key`. List APIs support pagination and documented filters.

## Companies

- `GET /api/v1/companies`
  - Filters: `search`, `ticker`, `is_active`, `industry`, `limit`, `offset`
  - Returns company summaries with filing count and latest filing status.
- `GET /api/v1/companies/{company_id}`
  - Returns company detail with ingestion status counts.

## Filings

- `GET /api/v1/companies/{company_id}/filings`
  - Filters: `form_type=10-Q`, `report_period_from`, `report_period_to`,
    `ingestion_status`, `limit`, `offset`
- `GET /api/v1/filings/{filing_id}/sections`
  - Returns section hierarchy and source references.
- `POST /api/v1/filings/{filing_id}/process`
  - Queues parser, table extraction, chunking, embedding, and indexing work.
  - Returns `202`.
- `GET /api/v1/filings/{filing_id}/processing-status`
  - Returns current stage, completed stages, failed stages, and errors.
- `GET /api/v1/filings/{filing_id}/sections/{section_id}`
  - Returns full section text and evidence metadata.
- `GET /api/v1/filings/{filing_id}/tables`
  - Returns extracted table summaries and normalized JSON.
- `GET /api/v1/filings/{filing_id}/chunks`
  - Returns paginated chunks without raw embedding arrays.

## Retrieval

- `POST /api/v1/retrieval/search`
  - Runs hybrid dense plus lexical retrieval and optional reranking.
- `POST /api/v1/retrieval/dense-search`
  - Diagnostic dense PGVector search.
- `POST /api/v1/retrieval/lexical-search`
  - Diagnostic PostgreSQL full-text search.

## Comparisons

- `POST /api/v1/comparisons`
  - Body: `current_filing_id`, `comparison_filing_id`
  - Validates same-company 10-Q filings with parsed sections/chunks.
  - Creates or reuses a versioned comparison and queues worker processing.
  - Returns `202` with `comparison_id`, `status`, and `job_id`.
- `GET /api/v1/comparisons`
  - Filters: `company_id`, `status`, `current_filing_id`,
    `comparison_filing_id`
  - Pagination: `limit`, `offset`
- `GET /api/v1/comparisons/{comparison_id}`
  - Returns status, processing metrics, version, filing IDs, and summary counts.
- `GET /api/v1/comparisons/{comparison_id}/section-matches`
  - Returns current/previous section IDs, match type, signal scores, confidence,
    reason metadata, and review status.
- `GET /api/v1/comparisons/{comparison_id}/passage-matches`
  - Returns current/previous passage IDs, alignment type, signal scores,
    confidence, and alignment metadata.
- `GET /api/v1/comparisons/{comparison_id}/changes`
  - Filters: `change_type`, `risk_category`, `min_materiality`, `review_status`
  - Pagination: `limit`, `offset`
- `GET /api/v1/comparisons/{comparison_id}/changes/{change_id}`
  - Returns one disclosure change with evidence, materiality components, model
    metadata, original model output, and review state.
- `PATCH /api/v1/comparisons/{comparison_id}/changes/{change_id}/review`
  - Body: `review_status`, optional `comment`, `reviewer_id`, `change_type`,
    `risk_category`, and `summary`
  - Preserves original classifier output while recording reviewer edits.

## Financial Claims

- `POST /api/v1/filings/{filing_id}/financial-claims/extract`
  - Queues deterministic/hybrid financial claim extraction for one filing.
  - Returns `202` with a worker job ID.
- `GET /api/v1/filings/{filing_id}/financial-claims`
  - Filters: `canonical_metric`, `limit`, `offset`
  - Returns extracted claims, normalized values, metric resolution, extractor
    metadata, original output, and review fields.
- `GET /api/v1/financial-claims/{claim_id}`
  - Returns one extracted financial claim.
- `GET /api/v1/financial-claims/{claim_id}/fact-candidates`
  - Returns preserved XBRL candidate facts and component scores.
- `PATCH /api/v1/financial-claims/{claim_id}/fact-candidates/{candidate_id}/review`
  - Body: optional `reviewer_id`, `comment`
  - Marks the chosen candidate as selected for its role and rejects competing
    candidates for the same claim/role.
- `POST /api/v1/financial-claims/{claim_id}/verify`
  - Queues deterministic verification for one claim.
  - Returns `202`.
- `GET /api/v1/financial-claims/{claim_id}/verification`
  - Returns the latest versioned verification row, formula, inputs, outputs,
    tolerance, confidence, and selected fact IDs.
- `PATCH /api/v1/financial-claims/{claim_id}/review`
  - Body: `review_status`, optional `comment`, `reviewer_id`,
    `canonical_metric_name`, `reported_value`, `reported_unit`, and
    `comparison_basis`
  - Preserves original extractor output while recording reviewer edits.
- `POST /api/v1/comparisons/{comparison_id}/financial-verification`
  - Queues financial claim extraction and verification for comparison evidence.
  - Returns `202`.
- `GET /api/v1/comparisons/{comparison_id}/financial-claims`
  - Filters: `filing_id`, `canonical_metric`, `limit`, `offset`
- `GET /api/v1/comparisons/{comparison_id}/financial-verifications`
  - Filters: `verification_status`, `min_confidence`

## Contradictions

- `POST /api/v1/comparisons/{comparison_id}/contradictions/analyze`
  - Queues deterministic narrative-data contradiction detection for one comparison.
  - Returns `202`.
- `GET /api/v1/comparisons/{comparison_id}/contradictions`
  - Filters: `contradiction_type`, `severity`, `risk_category`,
    `min_confidence`, `review_status`, `status`, `limit`, `offset`
  - Returns contradiction candidates with confidence, severity, evidence pointers,
    limitations, model metadata, and review fields.
- `GET /api/v1/comparisons/{comparison_id}/contradiction-summary`
  - Returns aggregate contradiction counts and severity distribution.
- `GET /api/v1/contradictions/{finding_id}`
  - Returns one contradiction finding with evidence and calculation output.
- `GET /api/v1/contradictions/{finding_id}/evidence`
  - Returns source passages, facts, derived metrics, and related evidence links.
- `PATCH /api/v1/contradictions/{finding_id}/review`
  - Body: `review_status`, optional `comment`, `reviewer_id`,
    `contradiction_type`, `severity`, `risk_category`, `summary`, and
    `explanation`.

## Analyses

- `POST /api/v1/analyses`
  - Body: `current_filing_id`, `comparison_filing_id`.
  - Creates or resumes an idempotent analysis.
- `GET /api/v1/analyses`
  - Filters: `company_id`, `status`, `current_filing_id`,
    `comparison_filing_id`, `limit`, `offset`
- `GET /api/v1/analyses/{analysis_run_id}`
  - Returns run metadata, workflow versions, status, and summary counts.
- `GET /api/v1/analyses/{analysis_run_id}/events`
  - Returns node-level workflow events, durations, attempts, and event payloads.
- `GET /api/v1/analyses/{analysis_run_id}/review`
  - Returns the latest pending or completed human review request for the run.
- `PATCH /api/v1/analyses/{analysis_run_id}/review`
- `POST /api/v1/analyses/{analysis_run_id}/review`
  - Body: `status`, optional `reviewed_by`, `comment`, and `review_payload`.
- `POST /api/v1/analyses/{analysis_run_id}/resume`
  - Resumes after human review or retryable failure.
- `GET /api/v1/analyses/{analysis_run_id}/report`
  - Returns the versioned generated analysis report, summaries, limitations, and
    evidence manifest.
- `POST /api/v1/analyses/{analysis_run_id}/cancel`
  - Cancels a cancellable workflow run.

## System

- `GET /api/v1/health`
  - Lightweight liveness check with service metadata.
- `GET /api/v1/ready`
  - Structured readiness check.
  - Returns `503` when configured dependency checks are degraded.
  - Does not expose credentials or full service URLs.

Deep health CLI:

```bash
cd backend
python -m app.cli.health all
```

## Status Codes

- `200` for successful reads and completed mutations.
- `201` for newly created resources.
- `202` for accepted background jobs.
- `400` for validation errors not covered by schema validation.
- `401` and `403` for authorization failures.
- `404` for missing resources.
- `409` for idempotency or invalid state conflicts.
- `422` for request schema validation errors.
- `429` for rate limits.
- `500` for unexpected server failures.
- `503` for dependency readiness failures.

## Phase 2.5 API Validation

Unit API tests verify the process endpoint returns `202`, request IDs are
preserved, retrieval responses include source-aware scores, and chunks do not
expose raw embedding arrays.

`tests/test_api_postgres_integration.py` is marker-gated and uses the real
PostgreSQL test database for `/api/v1/retrieval/search`. It inserts known
filing, section, and chunk rows, calls the HTTP route, and asserts dense,
lexical, fusion, reranker, and source metadata fields.

Run:

```bash
RUN_INTEGRATION_TESTS=1 RUN_POSTGRES_TESTS=1 python -m pytest -m "integration and postgres" -q
```

Phase 4 adds marker-gated PostgreSQL API coverage in
`tests/test_financial_postgres_integration.py`. It verifies claim extraction,
XBRL fact candidate persistence, versioned verification idempotency, derived
gross margin calculation, and financial-claim API reads/review against real
database rows.

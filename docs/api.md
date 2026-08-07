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
  - Filters: `ticker`, `is_active`, `industry`
  - Returns company summaries.
- `GET /api/v1/companies/{company_id}`
  - Returns company detail with ingestion summary.
- `POST /api/v1/companies/{company_id}/sync`
  - Starts SEC metadata and latest 10-Q sync through a worker job.
  - Requires `Idempotency-Key`.

## Filings

- `GET /api/v1/companies/{company_id}/filings`
  - Filters: `form_type=10-Q`, `report_period_from`, `report_period_to`, `ingestion_status`
- `GET /api/v1/filings/{filing_id}`
  - Returns filing metadata, source URL, storage state, parser version, and processing status.
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
- `GET /api/v1/filings/{filing_id}/xbrl-facts`
  - Filters: `concept`, `taxonomy`, `unit`, `fiscal_period`, `frame`

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

## Analyses

- `POST /api/v1/analyses`
  - Body: `company_id`, `current_filing_id`, `comparison_filing_id`, optional requested categories.
  - Creates or resumes an idempotent analysis.
- `GET /api/v1/analyses`
  - Filters: `company_id`, `status`, `created_from`, `created_to`
- `GET /api/v1/analyses/{analysis_id}`
  - Returns run metadata, workflow versions, status, and summary counts.
- `GET /api/v1/analyses/{analysis_id}/progress`
  - Returns node-level status, timing, retry count, partial outputs, and human-review interrupt state.
- `GET /api/v1/analyses/{analysis_id}/findings`
  - Filters: `risk_category`, `finding_type`, `severity`, `reviewer_status`
  - Sorts: `severity`, `confidence`, `created_at`
- `GET /api/v1/analyses/{analysis_id}/findings/{finding_id}`
  - Returns finding detail, source passages, XBRL facts, calculation, confidence, limitations, and audit history.
- `POST /api/v1/analyses/{analysis_id}/resume`
  - Resumes after human review or retryable failure.
  - Requires `Idempotency-Key`.

## Review

- `PATCH /api/v1/findings/{finding_id}/review`
  - Body: `reviewer_status`, optional edited title/summary/severity/comment.
  - Valid statuses: `approved`, `rejected`, `edited`, `uncertain`.
  - Creates audit event.

## Export

- `POST /api/v1/analyses/{analysis_id}/export`
  - Body: `format=json|pdf`
  - Requires all published findings to pass citation validation.
  - Requires `Idempotency-Key`.

## Evaluations

- `POST /api/v1/evaluations/run`
  - Body: dataset version, evaluators, thresholds.
  - Starts worker execution.
- `GET /api/v1/evaluations/runs`
  - Filters by dataset version, status, branch/commit when available.
- `GET /api/v1/evaluations/runs/{run_id}`
  - Returns metrics, threshold decisions, artifacts, and failed examples.

## System

- `GET /api/v1/health`
- `GET /api/v1/ready`
- `GET /api/v1/traces`
  - Restricted endpoint for dashboard-ready workflow and model traces.
- `GET /api/v1/audit-events`
  - Restricted endpoint for user/system audit history.

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

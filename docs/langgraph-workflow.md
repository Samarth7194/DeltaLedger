# LangGraph Production Workflow

Phase 6 connects the independently tested ingestion, processing, comparison,
financial verification, and contradiction services into one durable end-to-end
analysis workflow.

## Dependency Versions

The backend pins:

- `langgraph==1.1.3`
- `langgraph-checkpoint==4.0.1`
- `langgraph-checkpoint-postgres>=3.0.0,<4.0.0`

The Postgres checkpoint package is required for production durability. Local and
CI unit tests may use the installed memory checkpointer; production
configuration rejects memory-only checkpointing.

## Responsibilities

Dramatiq:

- starts and resumes long-running workflow execution
- isolates worker processes
- wraps catastrophic worker-level retries with bounded attempts

LangGraph:

- owns workflow state-machine routing
- persists compact execution state through checkpoints
- handles human interrupt and resume
- runs node-level orchestration

PostgreSQL business tables:

- `analysis_runs` stores user-visible workflow metadata
- `analysis_workflow_events` stores audit events
- `analysis_review_requests` stores workflow-level review gates
- `analysis_reports` stores authoritative structured reports

## State

`AnalysisState` contains IDs, status flags, counts, warnings, and routing
metadata:

- analysis, company, filing, comparison, review, and report IDs
- disclosure change, claim, verification, and contradiction finding IDs
- readiness flags
- evidence validation result
- review requirement/result
- warnings and safe error objects
- completed node list and compact counts

It does not store filings, sections, chunks, embeddings, large XBRL payloads, or
hidden model reasoning.

## Graph

```text
START
  -> validate_analysis_request
  -> ensure_filings_available
  -> ensure_filings_processed
  -> run_disclosure_comparison
  -> extract_financial_claims
  -> verify_financial_claims
  -> analyze_contradictions
  -> validate_evidence
  -> prioritize_findings
  -> review_gate
       -> generate_report
       -> finalize_analysis
       -> END
```

When review is required, `review_gate` persists an
`analysis_review_requests` row, records `workflow_interrupted`, sets the run to
`awaiting_human_review`, and calls LangGraph `interrupt`. Resume uses the same
checkpoint thread ID and a `Command(resume=...)` payload after review is
submitted.

`checkpoint_thread_id` is stored on `analysis_runs` and is unique per filing
pair plus workflow version. It is never included in public API response schemas.
The Postgres integration suite includes a focused interrupt/resume proof that
recreates the graph runtime and confirms work completed before the interrupt is
not rerun after resume.

## Node Contracts

Each node logs `node_started` and `node_completed` or `node_failed`, updates
`analysis_runs.current_node`, and writes compact metrics.

- `validate_analysis_request`: validates filing existence, same-company pair,
  newer current period, 10-Q support, and workflow version.
- `ensure_filings_available`: checks source availability and recoverable
  ingestion state without duplicating SEC ingestion logic.
- `ensure_filings_processed`: checks parsed sections and chunks, invoking
  `FilingProcessingService` only when storage exists and processing is missing.
- `run_disclosure_comparison`: calls `FilingComparisonService`; reuses existing
  version-compatible comparisons.
- `extract_financial_claims`: records currently persisted comparison claim IDs.
  The verification node invokes Phase 4 comparison verification, which performs
  version-compatible extraction where needed.
- `verify_financial_claims`: calls `FinancialVerificationService` and returns
  verification IDs and counts by status.
- `analyze_contradictions`: calls `ContradictionAnalysisService` and returns
  finding IDs and type counts.
- `validate_evidence`: checks source text, formulas, and primary contradiction
  evidence before review/reporting.
- `prioritize_findings`: assigns analyst-review priority only. It does not
  create investment scores.
- `review_gate`: applies configurable workflow review policy and interrupts
  when needed.
- `generate_report`: calls deterministic `AnalysisReportService`.
- `finalize_analysis`: marks completion or completion with warnings.

## Review Policy

Configurable settings:

- `WORKFLOW_REQUIRE_REVIEW_FOR_ALL_CONTRADICTIONS`
- `WORKFLOW_REVIEW_MIN_SEVERITY`
- `WORKFLOW_REVIEW_LOW_CONFIDENCE_THRESHOLD`
- `WORKFLOW_REVIEW_AMBIGUOUS_FINANCIAL_CLAIMS`

Review priority is for analyst workflow only:

- urgent
- high
- normal
- informational

It is separate from severity, confidence, and any investment meaning.

## Failure And Retry

Workflow failures are classified into safe categories such as validation error,
missing dependency, evidence validation error, recoverable database error, and
fatal internal error. Public API responses expose safe code/message/node fields
only.

Node logic is idempotent:

- comparisons reuse versioned comparison rows
- claims/verifications use Phase 4 idempotency
- contradiction findings use fingerprints
- reports upsert by analysis run

## Cancellation

Cancellation marks the run `cancelled`, records `workflow_cancelled`, preserves
completed work, and prevents new workflow starts from treating the run as
active. It does not hard-kill in-flight database transactions.

## Production Checkpointing

Production must use `WORKFLOW_CHECKPOINT_PROVIDER=postgres`. Memory
checkpointing is for local/unit tests only and is rejected by production
configuration. API and worker processes should share the same PostgreSQL-backed
checkpoint store so review interrupts can resume after process restarts.

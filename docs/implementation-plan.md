# Eight-Week Implementation Plan

## Week 1: Data Foundation

- Implement Docker Compose for PostgreSQL, PGVector, Redis, and MinIO.
- Add FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, structlog, and settings.
- Implement company, filing, and XBRL fact models plus migrations.
- Build SEC client with User-Agent, throttling, retries, timeouts, typed exceptions, and local caching.
- Add CLI skeletons for `ingest_company` and `seed_demo_data`.
- Tests: repository, migrations, SEC client mocks, duplicate filing behavior.

## Week 2: Filing Ingestion

- Download 10-Q primary documents from official SEC sources.
- Verify content type, compute SHA-256, store original documents in MinIO, and persist provenance.
- Track ingestion stages and failed-stage retries.
- Add idempotent worker jobs and dead-letter behavior.
- Tests: malformed SEC responses, duplicate filings, partial failures, worker retries.

## Week 3: Parsing And Indexing

- Parse filing HTML into sections, hierarchy, anchors, paragraphs, and tables where practical.
- Implement section-aware chunking with offsets, overlap, hashes, parser version, and provenance.
- Add embedding model interface, BGE-M3/local option, PGVector index, and retrieval APIs.
- Build initial filing viewer.
- Tests: parser, chunk boundaries, source references, embedding persistence, retrieval filters.

## Week 4: Temporal Comparison

- Implement hybrid retrieval with metadata filters, dense retrieval, lexical retrieval, fusion, and reranking. Status: complete in Phase 2.
- Implement section matching using normalized names, structure, similarity, reranker scores, position signals, and rule-based standard section matching. Status: complete in Phase 3 backend.
- Implement deterministic paragraph segmentation, monotonic passage alignment, semantic disclosure-change classification, materiality components, evidence persistence, and reviewer edits. Status: complete in Phase 3 backend.
- Tests: section matching, negative matches, passage alignment, change classification, review preservation, comparison API, and PostgreSQL persistence. Status: added for Phase 3.

## Week 5: Numerical Verification

- Implement financial metric dictionary and aliases.
- Extract structured financial claims.
- Resolve concepts, reporting periods, units, duration vs instant facts, quarterly vs year-to-date facts.
- Implement deterministic calculations with `Decimal` and reproducible formulas.
- Tests: metric mapping, wrong periods, wrong units, approximate verification, contradicted claims.

## Week 6: Contradiction Intelligence And Workflow

- Implement rule-based contradiction candidate generation. Status: complete in Phase 5 backend.
- Add model-assisted classification abstraction constrained to evidence. Status: fake/CI-safe provider complete in Phase 5 backend.
- Implement LangGraph state, nodes, routing, checkpointing, human interrupt, resume, node timing, and workflow events. Status: Phase 6 backend orchestration implemented locally.
- Add workflow-level review requests, evidence validation, analyst-review prioritization, cancellation, and deterministic structured report generation. Status: Phase 6 backend implemented locally.
- Tests: deterministic detector behavior, fixture distribution, workflow review policy, progress model, migration schema, standard backend suite. Status: added locally; real Postgres workflow validation requires local PostgreSQL availability.

## Week 7: Reports And Frontend

- Build dashboard, companies, filing detail, new comparison, progress, report, finding detail, evaluation dashboard, traces, and settings.
- Implement side-by-side evidence viewer, changed spans, XBRL evidence, calculations, reviewer controls, filters, sorting, empty/error/retry states.
- Implement JSON and PDF export with citation validation.
- Tests: component, query-state, finding review, analysis flow, Playwright E2E.

Status: Phase 7 analyst frontend is implemented as a Next.js workspace for
dashboard, company browsing, filing pair analysis creation, workflow progress,
events, disclosure comparison, financial verification, potential inconsistency
inspection, evidence viewing, workflow review, resume, and structured report
rendering. The MVP supports print-friendly reports and JSON download; server PDF
generation remains a later hardening item.

Phase 7.5 adds end-to-end acceptance hardening before Phase 8: real API
contract tests for analysis endpoints, Playwright browser coverage, development
CORS configuration, Postgres LangGraph checkpoint proof, dependency audit
commands, and a frontend E2E GitHub Actions workflow.

## Week 8: Evaluation, CI, And Hardening

- Build 150-example versioned benchmark dataset with human annotations.
- Implement metrics, evaluation dashboard, CI quality gates, and artifacts.
- Add GitHub Actions for backend, frontend, evaluation regression, and Docker build.
- Add security tests, load tests with Locust or k6, deployment docs, model card, limitations, and demo script.
- Run full test suite and record measured benchmark results in README.

Status: Phase 8 offline evaluation is implemented with versioned dataset
manifests, adapters for the existing Phase 3/4/5 fixtures, retrieval and
evidence seed datasets, deterministic metric functions, confidence calibration,
JSON/Markdown report generation, baseline comparison support, and an offline
evaluation CI workflow. It does not approve a baseline automatically.

## Phase 9: Production And Portfolio Readiness

- Harden production configuration and reject unsafe fallbacks.
- Add readiness checks, CLI dependency checks, security headers, and request IDs.
- Document migration-first deployment, separate API/worker startup, production
  checkpointing, Redis, object storage, and frontend configuration.
- Add deterministic demo setup and a concise interview walkthrough.
- Refresh README, portfolio case study, resume bullets, interview guide, and
  production checklist.

Status: Phase 9 prepares the project for deployment review and portfolio
presentation. It does not claim a completed remote deployment.

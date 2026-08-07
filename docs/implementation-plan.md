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

- Implement rule-based contradiction candidate generation.
- Add LLM-assisted classification and explanation constrained to evidence.
- Implement LangGraph state, nodes, routing, checkpointing, human interrupt, resume, node timing, and token usage.
- Tests: node behavior, routing, resumption, malformed LLM output, missing evidence abstention.

## Week 7: Reports And Frontend

- Build dashboard, companies, filing detail, new comparison, progress, report, finding detail, evaluation dashboard, traces, and settings.
- Implement side-by-side evidence viewer, changed spans, XBRL evidence, calculations, reviewer controls, filters, sorting, empty/error/retry states.
- Implement JSON and PDF export with citation validation.
- Tests: component, query-state, finding review, analysis flow, Playwright E2E.

## Week 8: Evaluation, CI, And Hardening

- Build 150-example versioned benchmark dataset with human annotations.
- Implement metrics, evaluation dashboard, CI quality gates, and artifacts.
- Add GitHub Actions for backend, frontend, evaluation regression, and Docker build.
- Add security tests, load tests with Locust or k6, deployment docs, model card, limitations, and demo script.
- Run full test suite and record measured benchmark results in README.

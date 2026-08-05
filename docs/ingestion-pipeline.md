# Ingestion Pipeline

## Scope

The ingestion pipeline uses official SEC sources only:

- SEC submissions API.
- SEC company facts/XBRL API.
- SEC filing document retrieval.
- SEC ticker/CIK lookup.

No unofficial scraping is used when SEC endpoints provide the data.

## Pipeline Stages

```text
fetch filing metadata
  -> check accession-number uniqueness
  -> download filing
  -> verify content type
  -> compute SHA-256 hash
  -> store original document
  -> parse document structure
  -> normalize sections
  -> extract tables where practical
  -> retrieve XBRL facts
  -> create semantic chunks
  -> generate embeddings
  -> store provenance
  -> mark ingestion complete
```

Phase 2 connects the post-download stages to `FilingProcessingService`, invoked by the
Redis-backed Dramatiq worker through `process_filing_task`.

Worker startup:

```bash
cd backend
python -m dramatiq app.workers.tasks
```

The worker opens and closes its own database session per job. Filing processing
uses a PostgreSQL advisory lock keyed by filing ID so two workers cannot process
the same filing concurrently. A duplicate job that cannot acquire the lock
returns an `already_running` status view rather than creating duplicate sections,
tables, chunks, or embeddings.

## Idempotency

- `accession_number` prevents duplicate filings.
- `content_hash` avoids reprocessing unchanged documents.
- Parser and embedding versions are stored so safe reprocessing can run when logic changes.
- Each stage records status, duration, and error details.
- Retry operates on failed stages only.
- Parser output replacement is idempotent: unchanged section hashes and parser versions
  reuse existing rows.
- Chunk replacement is idempotent: unchanged content hashes, parser versions, and
  chunker versions reuse existing rows and skip re-embedding when model metadata matches.

## SEC Reliability

- All requests use a configured SEC-compliant User-Agent.
- HTTP clients use timeouts, retries, throttling, and typed exceptions.
- Unsupported URLs are rejected by allowlisted SEC host validation.
- Raw SEC payloads are stored only when useful for provenance and diagnostics.

## CLI

Planned commands:

```bash
python -m app.cli.ingest_company --ticker AAPL --quarters 4
python -m app.cli.seed_demo_data
```

These commands enqueue idempotent worker jobs rather than doing long-running ingestion inside route handlers.

Processing endpoint:

```bash
POST /api/v1/filings/{filing_id}/process
```

Phase 2.5 parser fixtures are stored in `backend/tests/fixtures`. They include
one full unmodified SEC EDGAR 10-Q HTML fixture and several synthetic,
SEC-style, intentionally reduced 10-Q files for deterministic offline tests; see
`backend/tests/fixtures/provenance.md`.

For `APP_PROFILE=local-cloud`, raw filings are stored under
`OBJECT_STORAGE_LOCAL_ROOT` by `FilesystemObjectStorage`. MinIO remains available
for CI and Docker deployments through `OBJECT_STORAGE_PROVIDER=minio`.

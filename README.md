# DeltaLedger AI

Financial Disclosure Change and Contradiction Intelligence Platform

DeltaLedger AI is a portfolio-grade research tool for comparing SEC 10-Q disclosures across reporting periods. The system is designed to detect meaningful narrative and numerical changes, verify management claims against structured XBRL facts, identify potential contradictions between language and reported figures, and preserve exact evidence for every conclusion.

Portfolio message:

> I built a system that detects what changed between financial reporting periods, verifies whether management's numerical claims are supported by reported XBRL facts, identifies potential contradictions between narrative and data, and provides exact evidence for every conclusion.

## Current Status

Phase 2 backend foundation is implemented: SEC filing parsing, table extraction,
section-aware chunking, embedding/reranker abstractions, PGVector and PostgreSQL
full-text retrieval repositories, hybrid retrieval, processing worker integration,
and versioned retrieval/filing processing endpoints.

## MVP Scope

- 5 publicly listed US companies
- 4 quarterly 10-Q periods per company
- SEC filing HTML documents and SEC XBRL company facts
- 3 initial disclosure change categories: added, removed, strengthened/weakened language
- 3 initial risk categories: revenue and margin, liquidity and debt, customer concentration
- Evidence-grounded analysis report
- Human review workflow
- PostgreSQL with PGVector, Redis, filesystem or MinIO object storage, and optional Docker Compose

DeltaLedger AI is not a generic RAG chatbot, filing summarizer, stock-price predictor, trading recommender, or portfolio management system.

## Proposed Repository Structure

See [docs/repository-structure.md](docs/repository-structure.md).

## Architecture

See [docs/architecture.md](docs/architecture.md).

High-level flow:

```text
SEC APIs
  -> ingestion worker
  -> object storage and PostgreSQL
  -> parser, sectioning, chunking, embeddings
  -> hybrid retrieval and section matching
  -> disclosure diff, claim extraction, XBRL verification
  -> contradiction candidates and evidence assembly
  -> human review interrupt
  -> citation-validated report export
```

## Phase 2 Local Commands

```bash
cd backend
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check app tests --no-cache
python -m alembic upgrade head --sql
```

Docker-free local development:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
Set-Location backend
pip install -e ".[dev]"
Copy-Item ..\.env.example ..\.env
python -m alembic upgrade head
uvicorn app.main:app --reload
```

Run the worker in a second PowerShell terminal:

```powershell
Set-Location backend
.\..\.venv\Scripts\Activate.ps1
dramatiq app.workers.tasks
```

For `APP_PROFILE=local-cloud`, set managed PostgreSQL/PGVector and Redis URLs
in `.env`, use `OBJECT_STORAGE_PROVIDER=filesystem`, and keep
`EMBEDDING_PROVIDER=fake` unless using hosted Hugging Face inference:

```text
DATABASE_URL=postgresql+asyncpg://USER@HOST/DB?ssl=require
ALEMBIC_DATABASE_URL=postgresql+psycopg://USER@HOST/DB?sslmode=require
TEST_DATABASE_URL=postgresql+asyncpg://USER@HOST/DB_TEST?ssl=require
REDIS_URL=rediss://HOST:PORT
OBJECT_STORAGE_PROVIDER=filesystem
OBJECT_STORAGE_LOCAL_ROOT=./data/object-storage
```

For optional local Hugging Face model downloads:

```bash
python -m pip install -e ".[ai]"
```

Docker Compose remains supported for machines and deployment environments that
can run Docker, but it is not required for local laptop development.

## Phase 2.5 Infrastructure Validation

On Docker-capable machines, start local infrastructure from the repository root:

```bash
docker compose up -d postgres redis minio minio-init
docker compose ps
```

Run the API and worker in separate terminals:

```bash
cd backend
python -m alembic upgrade head
python -m uvicorn app.main:create_app --factory --reload --port 8000
```

```bash
cd backend
python -m dramatiq app.workers.tasks
```

Reset the local test database volume when a clean migration test is needed:

```bash
docker compose down
docker volume rm dk_postgres_data
docker compose up -d postgres
cd backend
python -m alembic upgrade head
```

MinIO runs at `http://localhost:9001` with the default local credentials from
`.env.example`. The compose init service creates `filings` and `reports` buckets.

Pytest markers:

```bash
cd backend
python -m pytest -m unit -q
RUN_INTEGRATION_TESTS=1 RUN_POSTGRES_TESTS=1 python -m pytest -m "integration and postgres" -q
RUN_INTEGRATION_TESTS=1 RUN_REDIS_TESTS=1 python -m pytest -m "integration and redis" -q
RUN_INTEGRATION_TESTS=1 RUN_MINIO_TESTS=1 python -m pytest -m "integration and minio" -q
RUN_LIVE_TESTS=1 python -m pytest -m live -q
RUN_MODEL_SMOKE=1 python -m pytest -m model_smoke -q
```

Standard tests stay offline and deterministic. The Hugging Face smoke tests are
manual because they download/load `BAAI/bge-m3` and `BAAI/bge-reranker-base`.
`RUN_MODEL_SMOKE_TESTS=1` is also accepted as an alias.

Current local validation note: the Phase 2.5 test suites and compose wiring have
been added, but this workstation did not have Docker available on `PATH`; local
PostgreSQL/PGVector and MinIO integration commands can only pass after those
services are running. Redis was available locally during validation.

## Phase 0 Review Packet

- [Architecture design](docs/architecture.md)
- [Database design](docs/database-design.md)
- [API contract](docs/api.md)
- [LangGraph workflow](docs/langgraph-workflow.md)
- [Evaluation methodology](docs/evaluation-methodology.md)
- [Ingestion pipeline](docs/ingestion-pipeline.md)
- [Retrieval design](docs/retrieval-design.md)
- [Section matching](docs/section-matching.md)
- [XBRL verification](docs/xbrl-verification.md)
- [Contradiction detection](docs/contradiction-detection.md)
- [Security](docs/security.md)
- [Deployment](docs/deployment.md)
- [Model card](docs/model-card.md)
- [Limitations](docs/limitations.md)
- [Repository structure](docs/repository-structure.md)
- [Eight-week implementation plan](docs/implementation-plan.md)
- [Risks and mitigations](docs/risks.md)

## Responsible Use

DeltaLedger AI is a research and financial-disclosure analysis tool. It does not provide investment advice, buy/sell/hold recommendations, or allegations of misconduct. Findings may be incomplete or incorrect, contradiction flags are potential inconsistencies, and human review is required. Original SEC filings remain the authoritative source.

# Repository Structure

This structure keeps DeltaLedger AI as a modular monolith for the MVP. Routes stay thin, repositories own data access, services own business logic, LangGraph nodes orchestrate typed services, and workers execute long-running jobs.

```text
.
|-- backend/
|   |-- app/
|   |   |-- api/
|   |   |   |-- routes/
|   |   |   `-- v1.py
|   |   |-- ai/
|   |   |   |-- graph/
|   |   |   |-- prompts/
|   |   |   `-- schemas/
|   |   |-- cli/
|   |   |-- core/
|   |   |-- db/
|   |   |   `-- models/
|   |   |-- integrations/
|   |   |   |-- sec/
|   |   |   |-- storage/
|   |   |   `-- tracing/
|   |   |-- repositories/
|   |   |-- services/
|   |   `-- workers/
|   |-- alembic/
|   `-- tests/
|-- frontend/
|   |-- app/
|   |-- components/
|   |-- features/
|   |-- lib/
|   |-- tests/
|   `-- e2e/
|-- data/
|   |-- evaluation/
|   `-- demo/
|-- docs/
|-- infra/
|   |-- docker/
|   `-- compose/
|-- scripts/
|-- .github/
|   `-- workflows/
|-- docker-compose.yml
|-- Makefile
`-- README.md
```

## Layer Responsibilities

Backend API routes validate HTTP input, call service interfaces, and return response envelopes. They do not contain business logic or direct SQLAlchemy queries.

Repositories encapsulate persistence, SQLAlchemy statements, locking/idempotency patterns, and transaction-aware reads/writes.

Services implement SEC ingestion, parsing, matching, verification, contradiction detection, report assembly, evaluation, and review workflows.

LangGraph nodes coordinate services through typed inputs and outputs. Nodes do not perform ad hoc data access.

Workers run ingestion, analysis, report export, and evaluation jobs. Jobs must be idempotent, retryable, observable, and safe to resume.

Frontend features mirror user workflows: companies, filings, comparisons, progress, findings, review, reports, evaluations, traces, and settings.

## Initial Scaffold Policy

Only directory placeholders are created in Phase 0. Application code, migrations, Docker Compose services, CI workflows, and tests should be implemented after design review.


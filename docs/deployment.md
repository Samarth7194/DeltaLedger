# Deployment

DeltaLedger is deployment-ready when the API, worker, PostgreSQL/PGVector,
Redis, object storage, frontend, migrations, and evaluation checks are all
configured explicitly. This document is provider-neutral; Vercel, Render,
Railway, Fly.io, AWS, GCP, Azure, Supabase, Neon, Upstash, and S3-compatible
storage can all fit the same shape.

## Architecture

```mermaid
flowchart LR
  Browser --> Frontend[Next.js]
  Frontend --> API[FastAPI API]
  API --> Postgres[(PostgreSQL + PGVector)]
  API --> Redis[(Redis)]
  API --> Storage[(S3-compatible object storage)]
  Worker[Dramatiq worker] --> Redis
  Worker --> Postgres
  Worker --> Storage
  Worker --> Providers[Model providers]
  API --> Providers
```

## Required Services

- PostgreSQL with the `vector` extension available.
- Redis reachable through `redis://` or `rediss://`.
- S3-compatible object storage for filing/report artifacts.
- A separately deployed FastAPI API process.
- A separately deployed Dramatiq worker process.
- Next.js hosting for the frontend.
- Optional model-provider credentials for real model-backed production runs.

## Environment Variables

Core:

```text
APP_PROFILE=production
ENVIRONMENT=production
LOG_LEVEL=INFO
LOG_JSON=true
CORS_ALLOWED_ORIGINS=https://your-frontend.example.com
FRONTEND_URL=https://your-frontend.example.com
READINESS_DEPENDENCY_CHECKS_ENABLED=true
AUTH_ENABLED=true
AUTH_SECRET_KEY=<32+ character secret from platform secret storage>
AUTH_TOKEN_TTL_SECONDS=3600
```

Database:

```text
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DB?ssl=require
ALEMBIC_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB?sslmode=require
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10
DATABASE_POOL_TIMEOUT_SECONDS=30
```

Redis and worker:

```text
REDIS_URL=rediss://USER:PASSWORD@HOST:PORT/0
REDIS_CONNECT_TIMEOUT_SECONDS=5
REDIS_SOCKET_TIMEOUT_SECONDS=5
```

Object storage:

```text
OBJECT_STORAGE_PROVIDER=minio
MINIO_ENDPOINT=https://s3-compatible-endpoint.example.com
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
MINIO_BUCKET_FILINGS=filings
MINIO_BUCKET_REPORTS=reports
```

Workflow and models:

```text
WORKFLOW_CHECKPOINT_PROVIDER=postgres
EMBEDDING_PROVIDER=...
RERANKER_ENABLED=true
RERANKER_PROVIDER=...
CHANGE_CLASSIFIER_PROVIDER=...
CLAIM_EXTRACTOR_PROVIDER=...
CONTRADICTION_CLASSIFIER_PROVIDER=...
ALLOW_FAKE_MODELS_IN_PRODUCTION=false
HF_TOKEN=...
```

SEC:

```text
SEC_USER_AGENT=DeltaLedgerAI/0.1 maintainer@example.com
SEC_REQUEST_TIMEOUT_SECONDS=20
SEC_MAX_ATTEMPTS=3
SEC_REQUESTS_PER_SECOND=5
```

Frontend:

```text
NEXT_PUBLIC_API_BASE_URL=https://your-api.example.com/api/v1
```

Do not store real credentials in tracked files. Use deployment platform secrets
or environment-variable managers.

## Database Preparation

PostgreSQL is the authoritative database. Application code must not create the
schema automatically in production; migrations are the source of truth.

Deployment order:

1. Install backend dependencies.
2. Validate environment variables.
3. Run `python -m alembic upgrade head` once.
4. Start the API service.
5. Start the worker service.

The API and workers should not all race to run migrations. Use one migration
job or release step.

## PGVector

The initial migration includes `CREATE EXTENSION IF NOT EXISTS vector`. Managed
providers may require enabling the extension manually or granting extension
permissions before migrations run.

Validate:

```bash
cd backend
python -m alembic upgrade head --sql
python -m app.cli.health pgvector
```

## Redis

Redis backs Dramatiq queues. Production must use a reachable managed Redis or
self-hosted Redis endpoint. `rediss://` is supported for TLS-backed providers.
Do not silently switch to in-memory queues in production.

## Object Storage

Local development can use filesystem storage. Production requires
S3-compatible storage through the `minio` client configuration. Bucket names are
configured separately for filings and reports. Avoid logging presigned URLs.

## Backend Deployment

API command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Container default:

```bash
docker build -t deltaledger-api backend
docker run --env-file .env -p 8000:8000 deltaledger-api
```

Liveness health check:

```text
/api/v1/health
```

Readiness health check:

```text
/api/v1/ready
```

## Worker Deployment

Worker command:

```bash
dramatiq app.workers.tasks
```

Run workers as a separate service from the API. Tune worker process count at the
platform level. Each task creates its own SQLAlchemy async session and uses
PostgreSQL advisory locks for duplicate workflow prevention.

## Frontend Deployment

Use Node `20.20.x`, `npm ci`, and `npm run build`. The frontend is configured
for Next.js `16.3.0` standalone output. Set `NEXT_PUBLIC_API_BASE_URL` to the
public API URL before building.

## Health Checks

- `/api/v1/health` is lightweight liveness and returns service metadata.
- `/api/v1/ready` returns structured dependency status and 503 when degraded.
- `python -m app.cli.health all` checks config, database, PGVector, Redis,
  storage configuration, and checkpoint configuration.

## Smoke Tests

After deploying:

```bash
cd backend
python -m app.cli.production_audit
python -m app.cli.health all
python -m app.cli.evaluate --suite all --offline
```

Then verify:

- API docs load at `/api/docs`.
- Frontend can call `/api/v1/health`.
- Protected API calls return `401` without a bearer token and `403` for an
  insufficient role.
- Worker imports with `dramatiq app.workers.tasks`.
- A deterministic demo manifest prints with
  `python -m app.cli.seed_demo_data --manifest-only`.

## Rollback Considerations

- Do not downgrade migrations automatically.
- Keep database backups before applying schema changes.
- Roll back API and worker images together when model/config contracts change.
- Keep evaluation reports and logs for failed releases.

## Troubleshooting

- 503 readiness: inspect the named check in the response.
- Migration failure: verify `ALEMBIC_DATABASE_URL` uses a synchronous driver.
- PGVector failure: enable `vector` extension privileges.
- Redis failure: verify `redis://` vs `rediss://`, TLS settings, and firewall rules.
- Worker idle: verify `REDIS_URL` matches API/worker configuration.
- Frontend API errors: verify `NEXT_PUBLIC_API_BASE_URL` and CORS origins.
- SEC errors: verify `SEC_USER_AGENT` includes real contact information.

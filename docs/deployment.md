# Deployment

## Local MVP

The MVP supports Docker-free local development and Docker Compose deployment.
On laptops that cannot run Docker, use `APP_PROFILE=local-cloud`:

- FastAPI backend.
- PostgreSQL/PGVector via a managed connection.
- Redis via a managed `redis://` or `rediss://` URL.
- Filesystem object storage at `OBJECT_STORAGE_LOCAL_ROOT`.
- Direct PowerShell API and Dramatiq worker processes.

## Docker-Free Local Startup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
Set-Location backend
pip install -e ".[dev]"
Copy-Item ..\.env.example ..\.env
python -m alembic upgrade head
uvicorn app.main:app --reload
```

Worker terminal:

```powershell
Set-Location backend
.\..\.venv\Scripts\Activate.ps1
dramatiq app.workers.tasks
```

Redis health check:

```powershell
python -m app.cli.health redis
```

Managed PostgreSQL configuration uses separate URLs:

```text
DATABASE_URL=postgresql+asyncpg://USER@HOST/DB?ssl=require
ALEMBIC_DATABASE_URL=postgresql+psycopg://USER@HOST/DB?sslmode=require
TEST_DATABASE_URL=postgresql+asyncpg://USER@HOST/DB_TEST?ssl=require
```

Destructive migration tests refuse to run unless the test database is separate
and its name contains `test`.

## Docker Startup

From the repository root:

```bash
docker compose config
docker compose up -d postgres redis minio minio-init
docker compose ps
```

The services use named volumes:

- `postgres_data`
- `redis_data`
- `minio_data`

Inside containers, backend and worker use service hostnames such as `postgres`,
`redis`, and `minio`. Host-side `.env.example` uses `localhost` ports for local
CLI and test execution.

For Docker Compose, set `DOCKER_DATABASE_URL` and `DOCKER_ALEMBIC_DATABASE_URL`
in the ignored `.env` file with the internal `postgres` hostname.

Run migrations and start the API:

```bash
cd backend
python -m alembic upgrade head
python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

Run the worker:

```bash
cd backend
python -m dramatiq app.workers.tasks
```

The worker uses Redis-backed Dramatiq and creates its own SQLAlchemy async
session for each job.

## Database Reset

For a destructive local reset:

```bash
docker compose down
docker volume rm dk_postgres_data
docker compose up -d postgres
cd backend
python -m alembic upgrade head
```

Use the test database for integration tests:

```bash
DATABASE_URL=postgresql+asyncpg://deltaledger@localhost:5433/deltaledger_test python -m alembic upgrade head
```

## MinIO

MinIO API endpoint:

```text
http://localhost:9000
```

MinIO console:

```text
http://localhost:9001
```

Default local credentials are `minioadmin` / `minioadmin`. The `minio-init`
compose service creates the `filings` and `reports` buckets.

## Validation Commands

```bash
cd backend
python -m pytest -q
python -m pytest -m unit -q
RUN_INTEGRATION_TESTS=1 RUN_POSTGRES_TESTS=1 python -m pytest -m "integration and postgres" -q
RUN_INTEGRATION_TESTS=1 RUN_REDIS_TESTS=1 python -m pytest -m "integration and redis" -q
RUN_INTEGRATION_TESTS=1 RUN_MINIO_TESTS=1 python -m pytest -m "integration and minio" -q
python -m ruff check app tests --no-cache
python -m alembic upgrade head
python -m alembic current
```

Manual smoke tests:

```bash
RUN_LIVE_TESTS=1 python -m pytest -m live -q
RUN_MODEL_SMOKE=1 python -m pytest -m model_smoke -q
```

Live SEC and model smoke tests are intentionally excluded from standard CI.
`RUN_MODEL_SMOKE_TESTS=1` is accepted as an alias for manual model smoke runs.

## Configuration

Configuration is environment-based. Required categories:

- Database URL.
- Redis URL.
- Object storage endpoint and credentials.
- SEC User-Agent.
- Hosted LLM provider credentials.
- Local/Hugging Face model configuration.
- Tracing backend configuration.
- Rate-limit and retry settings.

## Cloud Option

Cloud deployment documentation can later map local services to:

- Managed PostgreSQL with PGVector.
- Managed Redis.
- S3-compatible object storage.
- Container service for API and workers.
- Static/edge hosting for the Next.js frontend.
- OpenTelemetry-compatible tracing.

No production deployment should be claimed until migrations, tests, evaluation gates, security checks, and Docker builds pass.

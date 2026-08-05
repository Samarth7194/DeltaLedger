.PHONY: backend-install backend-test backend-test-unit backend-test-postgres backend-test-redis backend-test-minio backend-test-model backend-lint db-up db-down migrate ingest-demo

backend-install:
	cd backend && python -m pip install -e ".[dev]"

backend-test:
	cd backend && python -m pytest

backend-test-unit:
	cd backend && python -m pytest -m unit -q

backend-test-postgres:
	cd backend && RUN_INTEGRATION_TESTS=1 RUN_POSTGRES_TESTS=1 python -m pytest -m "integration and postgres" -q

backend-test-redis:
	cd backend && RUN_INTEGRATION_TESTS=1 RUN_REDIS_TESTS=1 python -m pytest -m "integration and redis" -q

backend-test-minio:
	cd backend && RUN_INTEGRATION_TESTS=1 RUN_MINIO_TESTS=1 python -m pytest -m "integration and minio" -q

backend-test-model:
	cd backend && RUN_MODEL_SMOKE=1 python -m pytest -m model_smoke -q

backend-lint:
	cd backend && python -m ruff check app tests

db-up:
	docker compose up -d postgres redis minio

db-down:
	docker compose down

migrate:
	cd backend && python -m alembic upgrade head

ingest-demo:
	cd backend && python -m app.cli.seed_demo_data --quarters 4

# Production Checklist

Use this before claiming a deployment is ready.

## Services

- [ ] PostgreSQL is reachable.
- [ ] `vector` extension is enabled.
- [ ] Alembic migration is at head.
- [ ] Redis is reachable through `redis://` or `rediss://`.
- [ ] Object storage buckets exist.
- [ ] API and worker use the same database, Redis, and storage settings.
- [ ] LangGraph checkpoint provider is `postgres`.

## Configuration

- [ ] `APP_PROFILE=production`.
- [ ] `ENVIRONMENT=production`.
- [ ] `READINESS_DEPENDENCY_CHECKS_ENABLED=true`.
- [ ] `AUTH_ENABLED=true`.
- [ ] `AUTH_SECRET_KEY` is set from secret storage and is not a placeholder.
- [ ] `CORS_ALLOWED_ORIGINS` contains only HTTPS frontend origins.
- [ ] `SEC_USER_AGENT` contains real contact information.
- [ ] Production does not use filesystem object storage.
- [ ] Production does not use memory checkpointing.
- [ ] Fake model providers are disabled unless explicitly approved for a demo.

## Smoke Tests

- [ ] `GET /api/v1/health` returns `status=ok`.
- [ ] `GET /api/v1/ready` returns `status=ready`.
- [ ] `python -m app.cli.production_audit` passes.
- [ ] `python -m app.cli.production_doctor` reports no blocked checks.
- [ ] `python -m app.cli.health all` passes.
- [ ] Worker imports with `dramatiq app.workers.tasks`.
- [ ] Frontend uses the deployed `NEXT_PUBLIC_API_BASE_URL`.
- [ ] Demo manifest prints with `python -m app.cli.seed_demo_data --manifest-only`.
- [ ] A demo analysis can be reviewed and resumed.
- [ ] A report is generated with evidence references.

## Security

- [ ] No secrets are committed.
- [ ] Secrets are set through deployment platform secret storage.
- [ ] Logs do not expose DB URLs, Redis credentials, object-storage secrets, tokens, or signed URLs.
- [ ] Review/resume/cancel routes require reviewer or admin role.
- [ ] Analyst-only tokens cannot submit reviews or resume workflows.
- [ ] Dependency audit status is reviewed and documented.

## Release

- [ ] Backend pytest passes.
- [ ] Ruff passes.
- [ ] Alembic SQL generation passes.
- [ ] Offline evaluation passes.
- [ ] Frontend lint, typecheck, tests, build, and Playwright pass.
- [ ] Rollback image/version is available.

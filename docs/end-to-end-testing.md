# End-To-End Testing

Phase 7.5 validates the analyst workspace against the real FastAPI contract and
the production workflow durability requirements without starting Phase 8 feature
work.

## Browser Contract

Playwright tests live in `frontend/e2e`. They mock the backend at the HTTP
boundary using the same response envelope and field names as the FastAPI
schemas. The critical browser flow covers:

- company list and company detail navigation
- filing pair selection and invalid pair prevention
- analysis creation
- workflow status transitions through `awaiting_human_review`
- disclosure, financial verification, contradiction, and evidence tabs
- review submission and resume
- completed report rendering and JSON download
- console errors, page errors, and unexpected API error responses

Run locally:

```powershell
Set-Location frontend
npm run test:e2e
```

Use Node `20.20.x` for build/dev validation. CI pins Node `20.20.2` so the
Next.js, Vite, Vitest, and Playwright toolchain runs on the same supported
runtime used for local production-build validation.

If the workspace denies Playwright artifact directory creation, redirect the
generated report and trace output to a writable temp directory:

```powershell
$env:PLAYWRIGHT_OUTPUT_DIR = "$env:TEMP\deltaledger-playwright-results"
$env:PLAYWRIGHT_HTML_REPORT = "$env:TEMP\deltaledger-playwright-report"
npx playwright test
```

Install Chromium first on a fresh machine:

```powershell
Set-Location frontend
npx playwright install chromium
```

## API Contract Checks

Backend contract tests exercise the Phase 6 analysis API endpoints with
schema-shaped service/repository fakes:

- `POST /api/v1/analyses`
- `GET /api/v1/analyses`
- `GET /api/v1/analyses/{analysis_run_id}`
- `GET /api/v1/analyses/{analysis_run_id}/events`
- `GET /api/v1/analyses/{analysis_run_id}/review`
- `POST /api/v1/analyses/{analysis_run_id}/review`
- `POST /api/v1/analyses/{analysis_run_id}/resume`
- `GET /api/v1/analyses/{analysis_run_id}/report`

Public analysis responses intentionally do not expose
`checkpoint_thread_id`. That value is an internal database/workflow durability
key only.

## Runtime Hardening

The frontend guards against partial API data with safe formatters and empty
states. Date formatting returns `Not available` for missing or invalid values,
and report rendering includes review outcomes when the API returns them.

Development CORS allows the Next.js app at `http://localhost:3000` and
`http://127.0.0.1:3000`. Production rejects wildcard CORS origins.

## LangGraph Checkpoints

Production workflow checkpointing uses `langgraph-checkpoint-postgres` with a
real Postgres saver. The Postgres-marked integration proof compiles a small
LangGraph probe, interrupts it, verifies checkpoint rows for the analysis
thread, recreates the graph runtime, resumes with `Command(resume=...)`, and
asserts that the pre-interrupt node did not rerun.

Run with a migrated test database:

```powershell
Set-Location backend
$env:RUN_INTEGRATION_TESTS = "1"
$env:RUN_POSTGRES_TESTS = "1"
python -m pytest -m "integration and postgres" -q
```

## Audit And Validation

Frontend:

```powershell
Set-Location frontend
npm audit
npm audit --omit=dev
npm run lint
npm run typecheck
npm test
npm run build
npm run test:e2e
```

Backend:

```powershell
Set-Location backend
python -m ruff check app tests --no-cache --output-format=github
python -m pytest -q
python -m alembic upgrade head --sql
```

No forced dependency upgrades should be applied from `npm audit fix --force`.

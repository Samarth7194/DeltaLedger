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

## Resuming The AAPL Run (`d70cad96-ff58-4f55-a597-fb2716ef72f3`)

This procedure continues the one existing analysis run end to end. It never creates a
new `analysis_runs` row. Read `python -m app.cli.preflight_e2e` output before doing
anything else - it never mutates data, never calls Gemini, and never enqueues a job.

### Preflight, as of this writing

```text
[DATABASE]  WARN  connectivity_and_schema   database reachable but schema validation is incomplete
            (alembic_current=0006_phase6_workflow, alembic_expected_head=0007_stage_batches,
             missing_tables=[analysis_stage_batches])
[REDIS]     PASS  connectivity              reachable
[WORKFLOW]  PASS  checkpoint_provider / analysis_time_limit / stage_batch_ledger
[AI]        PASS  embedding_provider, generative_model, batch_configuration, chat_pacing
[STORAGE]   PASS  provider, bucket_configuration
[SECURITY]  PASS  placeholder_values, auth_secret_strength
[SECURITY]  FAIL  no_localhost_in_production   production REDIS_URL points at localhost
OVERALL: FAIL
```

`python -m app.cli.production_doctor` additionally showed `ssl: disabled` on the database
connection metadata. Re-run both before the actual resume - this snapshot can go stale.

### What the run's actual state is (read-only check, no mutation)

A direct read of `analysis_runs` for this id shows:

```text
status = verifying_claims
current_node = verify_financial_claims
checkpoint_thread_id is set (a checkpoint exists)
analysis_review_requests: none for this run
```

**This changes the resume procedure.** The run is not paused for human review - it is
stuck mid-node, almost certainly because the worker process that was running it stopped
(quota exhaustion / crash / manual stop) before the node's own exception handler could run
and mark the run `failed`. Two consequences:

1. `POST /analyses/{id}/resume` refuses it: that endpoint requires
   `status == "awaiting_human_review"` ([analyses.py](../backend/app/api/routes/analyses.py)).
2. `POST /analyses/{id}/retry` also refuses it: that endpoint requires
   `status == "failed"`.

Today, no API endpoint accepts a run stuck in a non-terminal, non-review status. The only
way to continue *this exact run* is to re-enqueue it the same way `retry_analysis` does
internally - `enqueue_run_analysis_workflow(run_id)` - bypassing the HTTP status guard.
This is safe: it is the same function a normal retry calls, it passes the existing run id
(never creates a row), and every node the graph re-enters
(`validate_analysis_request` .. `extract_financial_claims`) is idempotent - it checks
persisted state and skips redoing completed work; the stage-batch ledger does the same for
`verify_financial_claims` onward. This is exactly what
`tests/test_stage_batch_postgres_integration.py` and `tests/test_comparison_batch_resume.py`
already prove offline. **This is a real, documented gap, not a new feature** - flagging it
here rather than quietly working around it.

### What I need from you before running this

- **A hosted `REDIS_URL`** (e.g. Upstash, Redis Cloud). Production currently points at
  `localhost:6379`, which does not exist where the worker runs; nothing below works until
  this is a real reachable Redis. I will not invent one or leave it as localhost.
- **Confirm Gemini quota/billing is available right now.** The Step 5 live evaluation in
  this sprint already made 92 real chat-completion calls (~43,600 tokens) against
  `gemini-3.5-flash-lite` on the same `AI_PROVIDER_API_KEY` production would use. If there
  is a daily cap, part of it is already spent today.
- **Optional, only if you also want the disposable-Postgres integration suite run as part
  of validation:** a `TEST_DATABASE_URL` that passes `tests.env_isolation.assert_safe_test_database`
  (disposable, name contains "test", not the application database).

### Command sequence (none of this has been run)

```powershell
# 1. Fix Redis, then re-check.
$env:REDIS_URL = "<hosted REDIS_URL you provide>"
Set-Location backend
python -m app.cli.preflight_e2e   # expect OVERALL: WARN or PASS, not FAIL

# 2. Apply the one pending migration (additive only: creates analysis_stage_batches
#    and its index; does not touch existing rows).
python -m alembic upgrade head
python -m app.cli.production_doctor   # database check should now read "ok", not "degraded"

# 3. Start the worker against the fixed REDIS_URL.
dramatiq app.workers.tasks

# 4. In a second shell, re-enqueue the EXISTING run (never creates a new one).
python - <<'PY'
import uuid
from app.workers.tasks import enqueue_run_analysis_workflow
job_id = enqueue_run_analysis_workflow(uuid.UUID("d70cad96-ff58-4f55-a597-fb2716ef72f3"))
print("enqueued:", job_id)
PY
```

### Proving durable resume (stop and restart the worker mid-run)

1. Watch progress without mutating anything, either through
   `GET /api/v1/analyses/d70cad96-ff58-4f55-a597-fb2716ef72f3/events` (if the API is also
   running) or a read-only query:
   ```sql
   SELECT stage, batch_index, total_batches, status, retry_count
   FROM analysis_stage_batches
   WHERE analysis_run_id = 'd70cad96-ff58-4f55-a597-fb2716ef72f3'
   ORDER BY stage, batch_index;
   ```
2. Once at least one batch shows `status = completed` and another shows `processing`,
   stop the worker (Ctrl+C, or `SIGTERM` the process) - simulating the exact kind of
   interruption that got this run stuck in the first place.
3. Restart it: `dramatiq app.workers.tasks`.
4. Re-run the same `enqueue_run_analysis_workflow(...)` snippet from step 4 above.
5. Confirm from the same query that the batches already `completed` before the stop keep
   their original `updated_at` / `retry_count` and are never resent to Gemini - only the
   batch that was `processing` (or `pending`) when the worker stopped does new provider
   work. This is the live version of what the stage-batch resume tests already assert.
6. Let it run to completion. If it reaches `awaiting_human_review`, submit
   `POST /api/v1/analyses/{id}/review` and then `POST /api/v1/analyses/{id}/resume` (now
   the normal, already-tested path, since the status guard matches).
7. Retrieve the finished report with `GET /api/v1/analyses/d70cad96-ff58-4f55-a597-fb2716ef72f3/report`.

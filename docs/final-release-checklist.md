# Final Release Checklist

## CODE

- [x] Backend API routes expose implemented resources only.
- [x] Worker tasks import cleanly in production profile smoke checks.
- [x] Frontend routes build under Next.js.
- [x] No TODO/debug-only release blockers were found in source scans.

## DATABASE

- [x] Alembic history is linear through revision `0006_phase6_workflow`.
- [x] `pgvector` extension setup remains in the initial migration.
- [x] Contradiction and workflow migrations include downgrade paths.
- [x] SQL offline generation reaches head without syntax failure.

## INFRA

- [x] Local environment templates are ignored except `.env.example`.
- [x] CI workflows cover backend, infrastructure, frontend E2E, and offline evaluation.
- [x] Docker image installs the backend package for production imports.
- [x] Generated frontend/backend artifacts are ignored.

## SECURITY

- [x] `.env` is ignored.
- [x] No staged commits were created during the audit.
- [x] Secret scan found only placeholders, test fixtures, and local defaults.
- [x] Health/readiness paths avoid exposing credential-bearing URLs.
- [x] Frontend production dependency audit passes after the Next.js 16.3.0
      upgrade.

## AI QUALITY

- [x] Evaluation fixtures and offline runner are present.
- [x] Metrics include precision, recall, false-positive rate, abstention, and severity accuracy.
- [x] Benchmark claims are documented as fixture/offline results, not production guarantees.
- [x] Model-smoke validation remains optional and credential gated.

## DEMO

- [x] Demo seed command supports deterministic local data.
- [x] Golden demo script and case study docs are present.
- [x] Frontend demo flow is covered by unit and Playwright tests.
- [x] Demo limitations are documented.

## GIT

- [x] No commit or push was performed by this audit.
- [x] Working tree remains available for manual review.
- [x] Suggested logical commit groups are documented in the final report.

## DEPLOYMENT

- [x] Production config validation rejects placeholder secrets.
- [x] Readiness checks can validate configured dependencies.
- [x] Deployment docs include required environment variables.
- [x] Remaining deployment work is limited to real environment provisioning and CI/deployment execution.
- [x] Frontend CI pins Node 20.20.2 and uses `npm ci`.

## PORTFOLIO

- [x] Portfolio claims are framed as engineering implementation and local validation.
- [x] Responsible-use limitations reject fraud, investment-advice, and autonomous compliance claims.
- [x] No development-assistant attribution artifacts were found.

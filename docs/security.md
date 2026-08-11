# Security And Reliability

## Controls

- Environment-based secrets.
- Input validation with Pydantic and Zod.
- SEC URL allowlists.
- Request timeouts.
- Rate limiting.
- Retry backoff.
- Circuit-breaker-ready abstractions.
- File and content-type validation.
- Safe HTML parsing.
- Prompt-injection-resistant retrieval instructions.
- Tool allowlists.
- Typed tool inputs.
- Authorization checks.
- Audit events.
- Signed object-storage URLs.
- Idempotency keys.
- Dead-letter jobs.
- Database transaction boundaries.
- Graceful shutdown.
- Health and readiness endpoints.

## Logging

Structured logs include request IDs, analysis IDs, node names, durations, retry counts, and error categories. Sensitive values, secrets, raw credentials, and hidden reasoning are never logged.

## Secret Management

- Keep `.env`, `.env.local`, generated credentials, DB passwords, Redis
  passwords, API tokens, object-storage secrets, and model-provider keys out of
  Git.
- Use deployment platform secret stores for production values.
- `.env.example` contains placeholders only.
- Do not print full database URLs, Redis URLs, presigned object-storage URLs, or
  provider tokens in logs or readiness responses.
- Before pushing, search for credential-like values with patterns covering
  `HF_TOKEN`, `PASSWORD`, authenticated Redis URLs, and PostgreSQL URLs.

## Production Configuration Safety

Production configuration fails fast when it detects:

- wildcard or localhost CORS origins
- filesystem object storage
- memory workflow checkpointing
- placeholder SEC contact details
- MinIO demo credentials
- fake model providers, unless explicitly overridden for a controlled demo

The production override for fake providers is intentionally explicit:
`ALLOW_FAKE_MODELS_IN_PRODUCTION=true`.

## Review And Resume Boundaries

Human-review and workflow-resume endpoints should be protected by application
authorization before public deployment. Current local/portfolio builds focus on
workflow correctness and do not claim multi-user authorization coverage.

## Safe Rendering

The frontend treats filing-derived content as data. Do not render untrusted SEC
HTML directly in the browser without sanitization. Evidence viewers should show
plain text, source anchors, hashes, and structured metadata.

## Dependency Vulnerabilities

Dependency audit results must be reported honestly. Safe compatible upgrades may
be applied, but forced major upgrades should be reviewed deliberately because
they can break Next.js, Playwright, or rendering behavior.

## Required Tests

- Unsupported URLs.
- Malformed SEC responses.
- Duplicate filings.
- Partial ingestion failures.
- Worker retries.
- Incorrect XBRL periods.
- Wrong units.
- Missing evidence.
- Invalid citations.
- Malformed LLM output.
- Analysis resumption after interruption.

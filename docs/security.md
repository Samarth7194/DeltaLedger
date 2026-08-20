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

- authentication disabled
- missing or placeholder `AUTH_SECRET_KEY`
- wildcard or localhost CORS origins
- filesystem object storage
- memory workflow checkpointing
- placeholder SEC contact details
- MinIO demo credentials
- fake model providers, unless explicitly overridden for a controlled demo

The production override for fake providers is intentionally explicit:
`ALLOW_FAKE_MODELS_IN_PRODUCTION=true`.

## Review And Resume Boundaries

Local and CI profiles keep `AUTH_ENABLED=false` by default so deterministic
tests and offline demos do not need secrets. Production requires
`AUTH_ENABLED=true` and a non-placeholder `AUTH_SECRET_KEY`.

Authentication uses short-lived HMAC-signed bearer tokens with role claims. The
frontend obtains those tokens through `POST /api/v1/auth/token` using
`AUTH_LOGIN_USERNAME` and `AUTH_LOGIN_PASSWORD`; the password is a deployment
secret and is not committed. `AUTH_SECRET_KEY` signs tokens and must not be used
directly as a browser token.

The token body is a base64url JSON payload containing `sub`, `role`, `iat`, and
`exp`, followed by a base64url HMAC-SHA256 signature:

```text
base64url(json-payload).base64url(hmac-sha256-signature)
```

The role hierarchy is:

- `analyst`: browse data, create analyses, run retrieval/processing workflows,
  and view findings, evidence, and reports.
- `reviewer`: analyst capabilities plus review submission, fact-candidate
  selection, workflow resume, and cancellation.
- `admin`: reviewer capabilities plus future administrative operations when
  such operations exist.

Protected operations return `401` when authentication is missing or invalid and
`403` when the authenticated role is insufficient. The current implementation
does not claim multi-tenancy or organization-level isolation.

### API Permission Matrix

| API surface | Required role | Notes |
| --- | --- | --- |
| Health and readiness | Public | Responses avoid credential-bearing URLs and detailed secrets. |
| Company and filing browsing | `analyst` | Covers company lists/details, filing status, sections, tables, and chunks. |
| Retrieval and analysis creation | `analyst` | Includes hybrid, dense, lexical search and analysis/comparison start routes. |
| Analysis, comparison, finding, evidence, and report reads | `analyst` | Sensitive analyst output is not anonymously readable in production. |
| Review submission, fact-candidate selection, resume, and cancel | `reviewer` | `admin` inherits reviewer capability through the role hierarchy. |

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

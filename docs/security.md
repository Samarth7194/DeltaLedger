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


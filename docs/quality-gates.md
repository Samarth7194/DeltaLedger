# Quality Gates

Phase 8 separates hard deterministic safety gates from semantic regression
reporting.

## Hard Gates

The offline workflow can fail on:

- invalid dataset manifests
- duplicate or malformed example IDs
- evaluated unsafe period match rate above zero
- evaluated unsafe unit acceptance rate above zero

If a metric cannot be evaluated, the gate reports `not_evaluated` rather than
inventing a pass/fail score.

## Semantic Gates

Retrieval, disclosure classification, contradiction precision, and other
semantic metrics are initially reporting-only unless an approved baseline is
provided.

Baseline comparison reports:

- absolute metric difference
- improved, regressed, or unchanged
- configurable floating-point tolerance

The repository includes a baseline directory, but no baseline is approved by
Phase 8 automatically.

## CI

`.github/workflows/evaluation-offline.yml` runs:

- backend install
- Ruff
- Phase 8 metric/runner tests
- offline benchmark generation
- evaluation report artifact upload

It does not weaken existing infrastructure, frontend, or model-smoke jobs.

The real SEC benchmark is included in the offline evaluation workflow, but it is
not a hard semantic gate until labels are human-approved and an approved
baseline exists. Candidate labels are validated for schema, traceability, split
consistency, and negative-control coverage.

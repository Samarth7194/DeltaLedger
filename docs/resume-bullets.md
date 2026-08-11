# Resume Bullets

## Short Version

- Built DeltaLedger AI, an evidence-grounded financial disclosure intelligence
  platform using FastAPI, PostgreSQL/PGVector, Redis/Dramatiq, LangGraph, and
  Next.js.
- Implemented cross-quarter 10-Q comparison, XBRL-backed financial claim
  verification, potential inconsistency detection, human review, and structured
  report generation.
- Added an offline evaluation suite covering retrieval metrics, classification
  metrics, confidence calibration, evidence quality, and CI quality gates.

## AI Engineer Version

- Designed hybrid retrieval with PostgreSQL full-text search, PGVector
  embeddings, reciprocal rank fusion, and optional cross-encoder reranking for
  evidence retrieval over SEC filing chunks.
- Built deterministic evaluation infrastructure for Recall@K, MRR, nDCG,
  macro/weighted F1, false-positive-rate paths, Brier score, ECE, and
  evidence-backed finding metrics.
- Separated model-assisted classification from deterministic XBRL arithmetic so
  numerical verification remains reproducible and auditable.

## Backend / SDE Version

- Built a production-oriented FastAPI backend with SQLAlchemy, Alembic,
  PostgreSQL/PGVector, Redis-backed Dramatiq workers, structured logging,
  health/readiness checks, and environment-based configuration.
- Implemented idempotent analysis orchestration with LangGraph checkpoints,
  PostgreSQL advisory locks, human-review interrupts, resume, and report
  persistence.
- Hardened deployment readiness with production config validation, separate API
  and worker startup commands, migration strategy, object-storage abstraction,
  and CI-ready evaluation gates.

## Portfolio Summary

DeltaLedger AI compares SEC financial disclosures across quarters, verifies
management claims against structured XBRL facts, surfaces potential
inconsistencies for analyst review, and generates evidence-backed reports with
responsible offline evaluation.

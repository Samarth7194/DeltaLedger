# Resume Bullets

## Short Version

- Built DeltaLedger AI, an evidence-grounded financial disclosure intelligence
  platform using FastAPI, PostgreSQL/PGVector, Redis/Dramatiq, LangGraph, and
  Next.js.
- Implemented cross-quarter 10-Q comparison, XBRL-backed financial claim
  verification, rule-based potential inconsistency detection, human review, and
  deterministic report generation.
- Added an offline evaluation harness (retrieval, classification, calibration and
  evidence metrics; CI quality gates) exercised on small author-written fixtures.

## AI Engineer Version

- Built a standalone hybrid search API (PostgreSQL full-text search, PGVector
  embeddings, reciprocal rank fusion, optional cross-encoder reranking) over SEC
  filing chunks. It is not part of the analysis pipeline, which uses BGE
  embeddings for section/passage matching.
- Implemented evaluation metric code (Recall@K, MRR, nDCG, macro/weighted F1,
  Brier score, ECE, evidence-backed finding rate) and ran it on small
  author-written fixtures with deterministic baselines. Real-model results are
  reported separately in docs/evaluation-suite.md.
- Separated model-assisted classification from deterministic XBRL arithmetic so
  numerical verification remains reproducible and auditable.

## Backend / SDE Version

- Built a production-oriented FastAPI backend with SQLAlchemy, Alembic,
  PostgreSQL/PGVector, Redis-backed Dramatiq workers, structured logging,
  health/readiness checks, and environment-based configuration.
- Implemented a linear 12-node LangGraph analysis pipeline with PostgreSQL
  checkpoints, advisory locks, one human-review interrupt, resume, and durable
  token-budgeted batch ledgers for LLM stages.
- Hardened deployment readiness with production config validation, separate API
  and worker startup commands, migration strategy, object-storage abstraction,
  and CI-ready evaluation gates.

## Portfolio Summary

DeltaLedger AI compares SEC financial disclosures across quarters, verifies
management claims against structured XBRL facts, surfaces potential
inconsistencies for analyst review, and generates evidence-backed reports with
responsible offline evaluation.

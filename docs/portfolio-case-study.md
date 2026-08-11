# Portfolio Case Study

## Problem

Financial filings change gradually across quarters. Analysts need to know what
changed, whether numerical claims are supported by reported facts, and where
evidence came from. Generic filing chat often retrieves plausible passages but
does not preserve evidence lineage or deterministic financial verification.

## Solution

DeltaLedger is an evidence-grounded disclosure intelligence platform. It
compares 10-Q disclosures, verifies financial claims against SEC XBRL facts,
surfaces potential inconsistencies, routes risky findings through human review,
and generates structured reports.

## Architecture

- FastAPI backend with typed routes and schemas.
- PostgreSQL with PGVector and full-text search.
- Redis-backed Dramatiq worker queue.
- LangGraph workflow orchestration with checkpoint/resume.
- S3-compatible or filesystem object storage abstraction.
- Next.js analyst workspace.
- Offline evaluation suite with deterministic quality gates.

## Key Engineering Challenges

- SEC HTML parsing requires stable section, table, and citation provenance.
- XBRL facts must be resolved by accession, period, unit, concept, and ambiguity.
- Quarter vs YTD and instant vs duration mistakes can create unsafe conclusions.
- Semantic comparison must avoid forcing unrelated passages together.
- Potential contradiction candidates need evidence and human review, not direct publication.
- Evaluation must report missing metrics honestly instead of filling placeholders.

## Retrieval Architecture

DeltaLedger uses dense embeddings, PostgreSQL full-text search, reciprocal rank
fusion, and optional reranking. The retrieval evaluator measures Recall@K,
Precision@K, MRR, nDCG, and hit rate for dense, lexical, hybrid, and reranked
systems.

## Financial Verification

Financial claims are resolved to canonical metrics and XBRL facts. Decimal
calculations verify reported values and changes. Unsafe period or unit matches
are treated as serious errors.

## Human-In-The-Loop

Potential inconsistencies can interrupt the workflow for analyst review.
Review decisions are persisted, the workflow resumes from a checkpoint, and the
final report records evidence references.

## Evaluation

Phase 8 adds versioned datasets, deterministic evaluators, confidence
calibration utilities, JSON/Markdown reports, and quality-gate support. Current
metrics are development benchmarks and not production validation.

## Production Architecture

Recommended deployment uses managed PostgreSQL/PGVector, managed Redis,
S3-compatible storage, a FastAPI API service, a separate Dramatiq worker
service, and a Next.js frontend. Production configuration rejects unsafe
fallbacks.

## Lessons Learned

- Deterministic finance logic belongs outside free-form model reasoning.
- Evidence lineage is a product feature, not just a debugging aid.
- Human review should be modeled as a first-class workflow state.
- Evaluation should make gaps visible instead of hiding them.

## Limitations

The current system focuses on 10-Q workflows, compact evaluation fixtures,
limited canonical metrics, and candidate inconsistency review. It does not
provide investment advice, fraud determinations, or production-scale validation.

## Future Work

- Broader labelled evaluation datasets.
- Additional financial metrics and issuer extension mappings.
- Authentication and multi-tenant authorization.
- Approved baselines and production monitoring.
- Real-model evaluation workflow with provider-cost tracking.

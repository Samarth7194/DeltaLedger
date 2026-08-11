# Interview Guide

## What Problem Does DeltaLedger Solve?

It helps analysts compare SEC disclosures across quarters, verify financial
claims against XBRL facts, surface potential inconsistencies, and inspect the
evidence behind every finding.

## Why Not Just Use An LLM Over The Filing?

Free-form LLM answers can miss period/unit issues, invent citations, or do
arithmetic unreliably. DeltaLedger uses models for semantic tasks but keeps
retrieval provenance, XBRL fact resolution, and calculations deterministic.

## Why Hybrid Retrieval?

Dense retrieval captures semantic similarity; lexical retrieval preserves exact
terms, accounting concepts, and issuer language. RRF combines both, and
reranking can improve ordering for review.

## Why PostgreSQL + PGVector + FTS?

The same database can store filings, chunks, facts, workflow state, audit data,
full-text indexes, and vectors. This keeps MVP deployment simpler than
introducing a separate vector database early.

## Why Deterministic Arithmetic?

Financial verification requires reproducibility. Decimal calculations and XBRL
inputs produce auditable results, while model output remains advisory.

## How Are XBRL Facts Resolved?

The resolver ranks candidate facts by canonical metric mapping, concept
priority, accession, period, unit, frame, and ambiguity margin. It abstains on
unsafe period or unit mismatches.

## How Do You Avoid Quarterly/YTD Errors?

Period behavior is modeled explicitly. Duration facts, instant facts,
same-period-prior-year comparisons, prior-quarter comparisons, and unsupported
annual periods are evaluated separately.

## How Are Disclosure Changes Detected?

The workflow matches sections, aligns passages, classifies change type, assigns
risk category, computes materiality components, and stores the source passages
for review.

## How Do You Reduce False Positives?

DeltaLedger preserves evidence, uses deterministic filters for numerical
claims, routes high-severity candidates through human review, and evaluates
false-positive-rate paths where negative controls exist.

## Why Human Review?

Potential inconsistencies can be subjective or context-dependent. The system
supports analyst approval, rejection, edits, uncertainty, workflow interrupts,
and checkpointed resume.

## Why LangGraph And Dramatiq?

LangGraph models the analysis as resumable workflow state. Dramatiq provides
background execution and retry behavior. The API process stays separate from
long-running analysis work.

## How Does Checkpoint/Resume Work?

Each analysis run has a stable checkpoint thread ID. Human review can interrupt
the graph, persist a review request, and resume after the review decision.
Production requires PostgreSQL checkpointing.

## How Is The System Evaluated?

Offline benchmark suites validate versioned datasets and calculate retrieval,
classification, calibration, evidence, and safety metrics. Missing labels or
predictions are reported as `not_evaluated` or `no_data`.

## What Happens With 1,000 Companies?

Scale ingestion and analysis through worker queues. Partition work by company
and filing period, cache parsed filings and embeddings, add backpressure for SEC
requests, and monitor queue depth and worker throughput.

## How Would Retrieval Indexes Scale?

Keep company/filing filters, tune PGVector indexes, batch embedding writes,
evaluate query latency, and consider a dedicated vector service only after
PostgreSQL limits become measurable.

## How Do You Prevent Duplicate Workflows?

The backend uses idempotent create paths, unique constraints, and PostgreSQL
advisory locks around workflow processing.

## How Would You Version Models And Prompts?

Persist provider, model name, model version, prompt version, evaluator version,
dataset version, and code version in outputs and evaluation reports.

## How Would You Reduce Model Cost?

Use deterministic filters first, cache embeddings, limit reranker candidates,
batch calls, abstain on low-value tasks, and evaluate model-backed features
separately from offline deterministic CI.

## How Would Multi-Tenancy Work?

Add tenant IDs to companies, filings, analyses, review requests, and reports;
enforce row-level authorization in repositories and API dependencies; partition
object-storage keys by tenant.

## Current Limitations

The system is not deployed remotely yet, benchmarks are compact, authentication
is not production-complete, and potential inconsistencies require analyst
review. It is not an investment advisor or fraud detector.

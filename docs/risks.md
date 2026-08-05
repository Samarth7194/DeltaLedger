# Major Risks And Mitigations

## SEC Filing Complexity

Risk: 10-Q HTML varies widely across companies and periods.

Mitigation: Preserve original documents, parser version, anchors, source references, and stage-level failure tracking. Start with five known companies, build parser fixtures, and support safe reprocessing.

## XBRL Period Ambiguity

Risk: Narrative claims may refer to quarterly, year-to-date, instant, duration, or non-GAAP values.

Mitigation: Use deterministic period resolution, explicit verification statuses, formula recording, and abstention when period or unit cannot be resolved.

## False Contradictions

Risk: The flagship feature can overflag normal financial nuance.

Mitigation: Generate candidates with rules first, require current/previous evidence and structured values, validate citations, expose limitations, and require human review before final publication.

## LLM Hallucination

Risk: LLMs may invent facts, citations, calculations, or unsupported explanations.

Mitigation: Use structured Pydantic outputs, evidence-only prompts, deterministic arithmetic, citation validation, prompt/version tracing, and abstention policies.

## Evaluation Ground Truth Quality

Risk: A weak dataset can make metrics misleading.

Mitigation: Require human-reviewed examples, include false-positive traps, version datasets, store annotation notes, and inspect failed examples in CI artifacts.

## Retrieval And Matching Drift

Risk: Embedding/reranker changes can silently degrade section matching.

Mitigation: Track model versions, retrieval traces, and regression gates for Recall@10 and section-match F1.

## Scope Creep

Risk: The project can become a generic finance assistant or trading product.

Mitigation: Keep the MVP constrained to 10-Q comparison, XBRL verification, contradiction candidates, evidence inspection, and review/export workflows.

## Operational Complexity

Risk: LangGraph, workers, object storage, vector search, and models create many failure modes.

Mitigation: Keep a modular monolith, add health/readiness endpoints, stage-level status, idempotent jobs, transaction boundaries, retries, dead-letter handling, and structured logs.


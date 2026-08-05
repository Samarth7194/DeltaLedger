# LangGraph State And Node Design

## State Model

The graph state is typed and persisted at checkpoints.

```text
AnalysisState
  analysis_run_id
  company_id
  current_filing_id
  comparison_filing_id
  workflow_version
  prompt_version
  model_configuration
  requested_risk_categories
  node_statuses
  section_match_ids
  disclosure_change_ids
  financial_claim_ids
  claim_verification_ids
  contradiction_finding_ids
  evidence_item_ids
  report_finding_ids
  human_review_required
  human_review_decisions
  error_code
  error_message
  processing_metrics
```

State stores identifiers and compact metadata, not large documents or hidden chain-of-thought. Full artifacts are retrieved through repositories.

## Required Nodes

### validate_analysis_request

- Inputs: filing IDs, company ID, requested categories.
- Outputs: normalized request and initial run status.
- Failure behavior: invalid company/filing relation, unsupported form type, same filing comparison.
- Retry behavior: not retryable for validation failures.
- Idempotency: keyed by analysis request and idempotency key.

### verify_filings_available

- Inputs: current and comparison filing IDs.
- Outputs: ingestion readiness.
- Failure behavior: routes to ingestion or failed state if filing cannot be retrieved.
- Retry behavior: retry SEC/storage transient failures.
- Idempotency: checks existing filing ingestion status.

### retrieve_comparable_sections

- Inputs: filing IDs and risk/section filters.
- Outputs: candidate section IDs and retrieval traces.
- Failure behavior: insufficient section coverage.
- Retry behavior: retry embedding/vector-store dependency failures.
- Idempotency: retrieval traces are versioned by retriever config.

### match_sections

- Inputs: candidate sections.
- Outputs: `section_matches`.
- Failure behavior: records low-confidence unmatched sections.
- Retry behavior: deterministic and reranker retries only.
- Idempotency: unique match keys prevent duplicates.

### detect_disclosure_changes

- Inputs: section matches.
- Outputs: `disclosure_changes`.
- Failure behavior: malformed model output is rejected and retried; deterministic no-change candidates are skipped.
- Retry behavior: retry structured LLM calls; deterministic diff is stable.
- Idempotency: stable section-match/change hash.

### extract_financial_claims

- Inputs: relevant current and previous sections.
- Outputs: `financial_claims`.
- Failure behavior: invalid structured outputs are dropped or retried.
- Retry behavior: retry model/provider failures.
- Idempotency: claim text hash plus source reference.

### verify_claims_against_xbrl

- Inputs: financial claims.
- Outputs: `claim_verifications`.
- Failure behavior: returns statuses such as `insufficient_data`, `ambiguous_metric`, `period_mismatch`, or `unit_mismatch`.
- Retry behavior: deterministic; only DB dependency failures retry.
- Idempotency: unique claim/fact/calculation signature.

### generate_contradiction_candidates

- Inputs: disclosure changes, claim verifications, XBRL facts, matched sections.
- Outputs: evidence-backed contradiction candidates.
- Failure behavior: abstains when evidence is incomplete.
- Retry behavior: deterministic candidate generation is stable.
- Idempotency: stable evidence/calculation hash.

### classify_risk_and_materiality

- Inputs: changes and candidates.
- Outputs: risk category, severity, materiality score, confidence.
- Failure behavior: structured output validation failure retries; unsupported categories rejected.
- Retry behavior: retry LLM classification calls.
- Idempotency: model/prompt version plus candidate hash.

### assemble_evidence

- Inputs: changes, claims, verifications, contradiction candidates.
- Outputs: `evidence_items`.
- Failure behavior: missing quote/fact/calculation blocks publication.
- Retry behavior: deterministic; DB failures retry.
- Idempotency: content hash and source reference.

### generate_report

- Inputs: evidence items and reviewed or pending findings.
- Outputs: draft `report_findings` and generated report object metadata.
- Failure behavior: abstains on unsupported claims.
- Retry behavior: retry model/report generation failures.
- Idempotency: report version and finding order.

### validate_report_citations

- Inputs: draft report findings.
- Outputs: citation validation results.
- Failure behavior: unsupported findings are withheld from final report.
- Retry behavior: deterministic; DB/storage failures retry.
- Idempotency: citation hash.

### human_review_interrupt

- Inputs: findings requiring review.
- Outputs: human decisions.
- Failure behavior: waits in interrupted state.
- Retry behavior: resume after decision.
- Idempotency: review action IDs and audit events.

### finalize_analysis

- Inputs: validated findings and review decisions.
- Outputs: completed analysis status and final report availability.
- Failure behavior: failed finalization retains draft and can retry.
- Retry behavior: retry storage/export failures.
- Idempotency: final report checksum and version.

## Routing

- Invalid requests route to terminal failure.
- Missing filing ingestion routes to ingestion job wait state.
- Low evidence routes to abstention rather than report generation.
- Human review routes to interrupt.
- Approved/edited findings route to citation validation and finalization.
- Rejected findings are excluded from final report but retained in audit history.

## Parallelism

Safe parallel branches:

- Section matching by section category.
- Disclosure change detection across section matches.
- Claim extraction across sections.
- XBRL verification across claims.
- Citation validation across findings.

All parallel branches write through repositories with stable idempotency keys.


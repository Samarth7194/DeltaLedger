# Database Design

## Principles

- PostgreSQL is the system of record for companies, filings, facts, analysis results, evidence, reviews, reports, audit events, and evaluation metadata.
- PGVector stores embeddings for filing chunks and retrieval traces where useful.
- MinIO/S3 stores original filings and generated report binaries; PostgreSQL stores object keys and checksums.
- Hard deletion is avoided for audit-critical analysis records. Soft deletion is only considered for user-facing saved views or draft objects introduced later.
- JSONB is used for source payloads, model configuration, structured evidence, and processing metrics when shape can evolve but indexed query paths are known.

## Core Tables

### companies

Stores normalized issuer identity.

Fields:

- `id`
- `cik`
- `ticker`
- `legal_name`
- `exchange`
- `industry`
- `fiscal_year_end`
- `is_active`
- `created_at`
- `updated_at`

Important constraints and indexes:

- `UNIQUE (cik)`
- `UNIQUE (ticker)` where ticker is not null
- Index on `(is_active, ticker)`

Primary queries:

- List active companies.
- Resolve ticker to CIK.
- Join filings and analysis runs by company.

### filings

Stores one SEC filing document per accession number.

Fields:

- `id`
- `company_id`
- `accession_number`
- `form_type`
- `filing_date`
- `report_period`
- `primary_document`
- `source_url`
- `storage_key`
- `content_hash`
- `ingestion_status`
- `parser_version`
- `raw_metadata`
- `created_at`
- `updated_at`

Important constraints and indexes:

- `FOREIGN KEY (company_id) REFERENCES companies(id)`
- `UNIQUE (accession_number)`
- `UNIQUE (company_id, form_type, report_period, accession_number)`
- Index on `(company_id, form_type, report_period DESC)`
- Index on `(ingestion_status, created_at)`
- JSONB GIN index on `raw_metadata` only for selected metadata diagnostics.

Primary queries:

- List 10-Q filings for a company.
- Find latest comparable filings.
- Check duplicate accession numbers before ingestion.

### filing_sections

Stores parsed section hierarchy and normalized text.

Fields:

- `id`
- `filing_id`
- `section_type`
- `section_title`
- `section_order`
- `parent_section_id`
- `raw_text`
- `normalized_text`
- `text_hash`
- `token_count`
- `page_or_anchor_reference`
- `metadata`
- `created_at`

Phase 2 fields:

- `part_number`
- `item_number`
- `canonical_section_type`
- `raw_start_offset`
- `raw_end_offset`
- `normalized_start_offset`
- `normalized_end_offset`
- `source_anchor`
- `native_element_id`
- `dom_path`
- `source_text_hash`
- `parser_version`

Important constraints and indexes:

- `FOREIGN KEY (filing_id) REFERENCES filings(id)`
- Self-reference `parent_section_id`.
- `UNIQUE (filing_id, section_order)`
- Index on `(filing_id, section_type, section_order)`
- Index on `(filing_id, part_number, item_number)`
- Index on `text_hash` for parser reprocessing and duplicate detection.

Primary queries:

- Render filing structure.
- Retrieve comparable sections by filing and section type.
- Validate quoted evidence against source text.

### filing_chunks

Stores retrieval chunks derived from sections.

Fields:

- `id`
- `filing_section_id`
- `chunk_index`
- `text`
- `embedding`
- `token_count`
- `start_offset`
- `end_offset`
- `source_reference`
- `metadata`
- `created_at`

Phase 2 fields:

- `content_hash`
- `source_text_hash`
- `parser_version`
- `chunker_version`
- `embedding_model`
- `embedding_version`
- `embedded_at`
- `search_vector`

Important constraints and indexes:

- `FOREIGN KEY (filing_section_id) REFERENCES filing_sections(id)`
- `UNIQUE (filing_section_id, chunk_index)`
- Index on `(filing_section_id, chunk_index)`
- PGVector index on `embedding` using HNSW or IVFFlat after embedding dimensions are finalized.
- GIN index on generated `search_vector` for PostgreSQL full-text retrieval.
- JSONB GIN index on `metadata` only for source-aware retrieval filters that cannot be represented as typed columns.

Primary queries:

- Dense retrieval under company, filing, period, form type, and section filters.
- Fetch chunks for a filing viewer and evidence inspection.

### filing_tables

Stores tables extracted from SEC filing HTML.

Fields:

- `id`
- `filing_id`
- `filing_section_id`
- `table_index`
- `caption`
- `raw_html`
- `normalized_json`
- `content_hash`
- `source_anchor`
- `native_element_id`
- `dom_path`
- `extraction_version`
- `metadata`
- `created_at`

Important constraints and indexes:

- `FOREIGN KEY (filing_id) REFERENCES filings(id)`
- Nullable `FOREIGN KEY (filing_section_id) REFERENCES filing_sections(id)`
- `UNIQUE (filing_id, table_index)`
- Index on `(filing_id, filing_section_id)`
- Index on `content_hash`
- JSONB GIN index on `metadata`

Primary queries:

- List tables for a filing.
- Associate financial tables with source sections.
- Validate table evidence.

### filing_processing_stages

Tracks parser/chunker/embedding worker progress.

Fields:

- `id`
- `filing_id`
- `stage_name`
- `status`
- `attempt_count`
- `started_at`
- `completed_at`
- `duration_ms`
- `error_code`
- `error_message`
- `metrics`
- `created_at`
- `updated_at`

Important constraints and indexes:

- `FOREIGN KEY (filing_id) REFERENCES filings(id)`
- `UNIQUE (filing_id, stage_name)`
- Index on `(filing_id, status)`

Primary queries:

- Show processing status by filing.
- Resume failed stages.
- Audit worker reliability and stage duration.

### xbrl_facts

Stores normalized SEC company facts linked to filings when accession metadata permits.

Fields:

- `id`
- `company_id`
- `filing_id`
- `taxonomy`
- `concept`
- `label`
- `unit`
- `value_numeric`
- `value_text`
- `start_date`
- `end_date`
- `instant_date`
- `fiscal_year`
- `fiscal_period`
- `form_type`
- `accession_number`
- `frame`
- `raw_fact`
- `created_at`

Important constraints and indexes:

- `FOREIGN KEY (company_id) REFERENCES companies(id)`
- Nullable `FOREIGN KEY (filing_id) REFERENCES filings(id)`
- Index on `(company_id, concept, fiscal_year, fiscal_period)`
- Index on `(filing_id, concept)`
- Index on `(accession_number, concept, unit)`
- Index on `(frame)`
- JSONB GIN index on `raw_fact` for diagnostics.

Primary queries:

- Resolve candidate concepts for a claim.
- Compare current and previous period values.
- Validate units, instant/duration periods, and frames.

## Phase 3 Comparison Tables

### filing_comparisons

Stores one versioned cross-quarter comparison request for a current 10-Q and a
previous 10-Q from the same company.

Key fields:

- `company_id`
- `current_filing_id`
- `comparison_filing_id`
- `status`
- `comparison_version`
- `matching_model_name`
- `matching_model_version`
- `change_model_name`
- `change_model_version`
- `processing_metrics`
- `error_code`
- `error_message`

Important constraints and indexes:

- `CHECK (current_filing_id <> comparison_filing_id)`
- `UNIQUE (current_filing_id, comparison_filing_id, comparison_version)`
- Index on `(company_id, current_filing_id, comparison_filing_id)`

### section_matches

Stores section pair decisions for a comparison. Matches can be structural,
semantic, hybrid, unmatched-current, or unmatched-previous.

Key fields:

- `comparison_id`
- `current_section_id`
- `previous_section_id`
- `match_type`
- `heading_similarity`
- `dense_similarity`
- `lexical_similarity`
- `reranker_score`
- `structural_score`
- `combined_score`
- `confidence`
- `match_reason`
- `review_status`

### passage_units

Stores deterministic paragraph-level units derived from parsed sections. Units
preserve offsets, source anchors, hashes, and segmentation version.

Key fields:

- `filing_section_id`
- `unit_type`
- `unit_index`
- `text`
- `normalized_text`
- `raw_char_start`
- `raw_char_end`
- `source_anchor`
- `content_hash`
- `segmentation_version`

Important constraint:

- `UNIQUE (filing_section_id, unit_type, unit_index, segmentation_version)`

### passage_matches

Stores monotonic passage alignment results for each matched section pair.

Key fields:

- `section_match_id`
- `current_passage_id`
- `previous_passage_id`
- `alignment_type`
- `dense_similarity`
- `lexical_similarity`
- `reranker_score`
- `sequence_score`
- `combined_score`
- `confidence`
- `alignment_metadata`

### disclosure_changes

Stores semantic disclosure findings generated from passage matches.

Key fields:

- `comparison_id`
- `section_match_id`
- `passage_match_id`
- `change_type`
- `risk_category`
- `previous_text`
- `current_text`
- `changed_spans`
- `change_summary`
- `change_explanation`
- `materiality_score`
- `confidence`
- `supporting_evidence`
- `materiality_components`
- `original_model_output`
- `model_name`
- `model_version`
- `prompt_version`
- `review_status`
- `review_comment`
- `reviewed_by`
- `reviewed_at`
- `reviewer_edits`

Reviewer edits intentionally do not overwrite `original_model_output`; the
system keeps classifier output and human changes separately for auditability.

## Phase 4 Financial Claim Verification Tables

Phase 4 adds deterministic financial-claim verification without creating a
second XBRL store. All fact matching references existing `xbrl_facts`.

### financial_metric_definitions

Canonical metric registry for metrics the system can resolve and verify.

Key fields:

- `canonical_name`
- `display_name`
- `metric_type`: monetary, percentage, ratio, per_share, or count
- `period_behavior`: duration, instant, or derived
- `preferred_unit_category`
- `description`
- `aliases`
- `is_active`

`canonical_name` is unique.

### financial_metric_concepts

Maps one canonical metric to ranked XBRL concept candidates.

Key fields:

- `metric_definition_id`
- `taxonomy`
- `concept`
- `priority`
- `period_behavior`
- `unit_category`
- `is_preferred`
- `is_active`
- `notes`

The resolver scores all serious concept candidates and does not assume one XBRL
concept works for every issuer.

### financial_claims

Stores structured claims extracted from narrative passages.

Key fields:

- `filing_id`
- `comparison_id`
- `disclosure_change_id`
- `source_section_id`
- `source_passage_id`
- `claim_text`
- `canonical_metric_name`
- `metric_definition_id`
- `claim_type`
- `direction`
- `reported_value`
- `reported_unit`
- `reported_change`
- `reported_change_unit`
- `comparison_basis`
- `comparison_text`
- `qualifiers`
- `extraction_confidence`
- `extraction_method`
- `original_model_output`
- `review_status`
- `reviewer_edits`

Indexes support `(filing_id, canonical_metric_name)`, `comparison_id`, and
`source_passage_id`.

### claim_fact_candidates

Preserves every serious fact considered by the resolver.

Key fields:

- `financial_claim_id`
- `xbrl_fact_id`
- `candidate_role`: current or comparison
- concept, period, unit, accession, frame, and combined scores
- `selection_status`: candidate, selected, rejected, or ambiguous
- `rejection_reason`

Candidates are replaced idempotently for a claim and role.

### claim_verifications

Stores authoritative Decimal-based verification output.

Key fields:

- `financial_claim_id`
- `current_xbrl_fact_id`
- `comparison_xbrl_fact_id`
- `verification_status`
- current/comparison values
- absolute, percentage, and percentage-point changes
- reported-vs-calculated difference
- `calculation_type`
- `formula`
- `calculation_inputs`
- `calculation_output`
- `tolerance_used`
- `verification_reason`
- `confidence`
- `verification_version`

`(financial_claim_id, verification_version)` is unique so processing can rerun
without duplicating results.

### derived_financial_metrics

Stores deterministic derived metrics such as gross margin.

Key fields:

- `metric_definition_id`
- `filing_id`
- `calculation_status`
- `formula`
- `input_fact_ids`
- `calculation_inputs_snapshot`
- `calculated_value`
- `unit`
- `period_type`
- `period_start`
- `period_end`
- `calculation_version`
- `assumptions`

Phase 4 implements gross margin as `GrossProfit / Revenue * 100` only when
facts have compatible units, matching accession numbers, matching periods, and
non-zero revenue.

### analysis_runs

Tracks a comparison workflow.

Fields:

- `id`
- `company_id`
- `current_filing_id`
- `comparison_filing_id`
- `status`
- `requested_by`
- `started_at`
- `completed_at`
- `workflow_version`
- `prompt_version`
- `model_configuration`
- `error_code`
- `error_message`
- `processing_metrics`
- `created_at`

Important constraints and indexes:

- `FOREIGN KEY (company_id) REFERENCES companies(id)`
- `FOREIGN KEY (current_filing_id) REFERENCES filings(id)`
- `FOREIGN KEY (comparison_filing_id) REFERENCES filings(id)`
- Index on `(company_id, created_at DESC)`
- Index on `(status, created_at)`
- Optional unique idempotency key in a later `idempotency_keys` table or API request table.

Primary queries:

- Show analysis history.
- Poll progress.
- Resume interrupted runs.

### section_matches

Stores section-to-section matches and scores.

Fields:

- `id`
- `analysis_run_id`
- `current_section_id`
- `comparison_section_id`
- `semantic_similarity`
- `lexical_similarity`
- `reranker_score`
- `match_method`
- `match_confidence`
- `reviewer_status`
- `created_at`

Important constraints and indexes:

- `FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs(id)`
- Foreign keys to current and comparison `filing_sections`.
- `UNIQUE (analysis_run_id, current_section_id, comparison_section_id)`
- Index on `(analysis_run_id, match_confidence DESC)`
- Index on `(reviewer_status)`

Primary queries:

- Show matched sections.
- Feed disclosure diff.
- Review or correct section matches.

### disclosure_changes

Stores narrative changes detected from matched sections.

Fields:

- `id`
- `analysis_run_id`
- `section_match_id`
- `change_type`
- `risk_category`
- `previous_text`
- `current_text`
- `semantic_explanation`
- `materiality_score`
- `confidence`
- `structured_evidence`
- `model_name`
- `model_version`
- `prompt_version`
- `reviewer_status`
- `reviewer_comment`
- `created_at`
- `updated_at`

Important constraints and indexes:

- `FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs(id)`
- Nullable `FOREIGN KEY (section_match_id) REFERENCES section_matches(id)`
- Index on `(analysis_run_id, risk_category, change_type)`
- Index on `(analysis_run_id, confidence DESC)`
- JSONB GIN index on `structured_evidence`.

Primary queries:

- Filter report findings by change type and risk category.
- Inspect changed spans and evidence.

### financial_claims

Stores extracted narrative claims.

Fields:

- `id`
- `analysis_run_id`
- `filing_id`
- `source_section_id`
- `claim_text`
- `metric_name`
- `period_reference`
- `reported_value`
- `unit`
- `direction`
- `qualifier`
- `extraction_confidence`
- `source_reference`
- `created_at`

Important constraints and indexes:

- `FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs(id)`
- `FOREIGN KEY (filing_id) REFERENCES filings(id)`
- `FOREIGN KEY (source_section_id) REFERENCES filing_sections(id)`
- Index on `(analysis_run_id, metric_name)`
- Index on `(filing_id, source_section_id)`

Primary queries:

- Review extracted claims.
- Feed XBRL verification.

### claim_verifications

Stores deterministic verification results for claims.

Fields:

- `id`
- `financial_claim_id`
- `xbrl_fact_id`
- `verification_status`
- `expected_value`
- `actual_value`
- `absolute_difference`
- `percentage_difference`
- `calculation_formula`
- `deterministic_result`
- `explanation`
- `confidence`
- `created_at`

Important constraints and indexes:

- `FOREIGN KEY (financial_claim_id) REFERENCES financial_claims(id)`
- Nullable `FOREIGN KEY (xbrl_fact_id) REFERENCES xbrl_facts(id)`
- Index on `(verification_status)`
- Index on `(financial_claim_id, verification_status)`

Primary queries:

- Show support, contradiction, ambiguity, unit mismatch, and period mismatch.
- Feed contradiction candidate generation.

### contradiction_findings

Stores evidence-backed potential inconsistencies.

Fields:

- `id`
- `analysis_run_id`
- `finding_type`
- `risk_category`
- `narrative_claim`
- `structured_fact_summary`
- `deterministic_calculation`
- `contradiction_reason`
- `severity`
- `confidence`
- `status`
- `reviewer_status`
- `reviewer_comment`
- `created_at`
- `updated_at`

Important constraints and indexes:

- `FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs(id)`
- Index on `(analysis_run_id, risk_category, severity)`
- Index on `(status, reviewer_status)`

Primary queries:

- Show flagship contradiction results.
- Route to human review.

### evidence_items

Stores reusable evidence records for passages, facts, calculations, and tables.

Fields:

- `id`
- `analysis_run_id`
- `evidence_type`
- `filing_id`
- `section_id`
- `xbrl_fact_id`
- `source_reference`
- `quoted_text`
- `structured_payload`
- `content_hash`
- `created_at`

Important constraints and indexes:

- `FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs(id)`
- Nullable foreign keys to filings, sections, and XBRL facts.
- Index on `(analysis_run_id, evidence_type)`
- Index on `(content_hash)`
- JSONB GIN index on `structured_payload`.

Primary queries:

- Validate report citations.
- Render evidence inspector.
- Reproduce calculations.

### report_findings

Stores publication-ready findings after citation validation.

Fields:

- `id`
- `analysis_run_id`
- `finding_order`
- `finding_type`
- `title`
- `summary`
- `risk_category`
- `severity`
- `confidence`
- `supporting_evidence_ids`
- `reviewer_status`
- `created_at`

Important constraints and indexes:

- `FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs(id)`
- `UNIQUE (analysis_run_id, finding_order)`
- Index on `(analysis_run_id, risk_category, severity)`
- `supporting_evidence_ids` should be represented as an array initially, with a join table added if evidence reuse queries become complex.

Primary queries:

- Render final report.
- Export reviewed findings.

### generated_reports

Stores generated report artifacts.

Fields:

- `id`
- `analysis_run_id`
- `format`
- `storage_key`
- `report_version`
- `generated_at`
- `generated_by_model`
- `checksum`

Important constraints and indexes:

- `FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs(id)`
- `UNIQUE (analysis_run_id, format, report_version)`
- Index on `(analysis_run_id, generated_at DESC)`

Primary queries:

- Download latest JSON/PDF report.
- Verify checksum and provenance.

## Evaluation Tables

`evaluation_datasets`, `evaluation_examples`, `evaluation_runs`, and `evaluation_results` store versioned benchmark examples, run metadata, metrics, thresholds, regression decisions, and artifacts.

### evaluation_datasets

Fields:

- `id`
- `name`
- `version`
- `description`
- `annotation_guidelines`
- `created_by`
- `created_at`
- `metadata`

Constraints and indexes:

- `UNIQUE (name, version)`
- Index on `(created_at DESC)`

### evaluation_examples

Fields:

- `id`
- `dataset_id`
- `example_type`
- `company`
- `filing_periods`
- `source_references`
- `expected_section_match`
- `expected_change_type`
- `expected_risk_category`
- `expected_numerical_values`
- `expected_calculation`
- `expected_contradiction_status`
- `human_annotations`
- `created_at`
- `metadata`

Constraints and indexes:

- `FOREIGN KEY (dataset_id) REFERENCES evaluation_datasets(id)`
- Index on `(dataset_id, example_type)`
- JSONB GIN indexes on `source_references` and `human_annotations` when query patterns justify them.

### evaluation_runs

Fields:

- `id`
- `dataset_id`
- `status`
- `started_at`
- `completed_at`
- `workflow_version`
- `prompt_version`
- `model_configuration`
- `threshold_configuration`
- `git_commit`
- `artifact_storage_key`
- `error_code`
- `error_message`
- `created_at`

Constraints and indexes:

- `FOREIGN KEY (dataset_id) REFERENCES evaluation_datasets(id)`
- Index on `(dataset_id, created_at DESC)`
- Index on `(status, created_at)`

### evaluation_results

Fields:

- `id`
- `evaluation_run_id`
- `example_id`
- `metric_name`
- `metric_value`
- `threshold_value`
- `passed`
- `details`
- `created_at`

Constraints and indexes:

- `FOREIGN KEY (evaluation_run_id) REFERENCES evaluation_runs(id)`
- Nullable `FOREIGN KEY (example_id) REFERENCES evaluation_examples(id)` for aggregate metrics.
- Index on `(evaluation_run_id, metric_name)`
- Index on `(passed, metric_name)`

Important indexes:

- Dataset version uniqueness.
- `(evaluation_run_id, metric_name)`
- `(dataset_id, example_type)`

## Audit Events

`audit_events` records user actions, system state transitions, review decisions, exports, retries, and security-relevant events.

Fields:

- `id`
- `event_type`
- `actor_id`
- `actor_type`
- `entity_type`
- `entity_id`
- `analysis_run_id`
- `request_id`
- `idempotency_key`
- `before_state`
- `after_state`
- `metadata`
- `created_at`

Constraints and indexes:

- Nullable `FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs(id)`
- Index on `(actor_id, created_at DESC)`
- Index on `(entity_type, entity_id)`
- Index on `(event_type, created_at DESC)`
- JSONB GIN index on `metadata` only for operational audit queries.

Important indexes:

- `(actor_id, created_at DESC)`
- `(entity_type, entity_id)`
- `(event_type, created_at DESC)`

## Phase 2.5 Migration Checks

The Phase 2 migration path is tested by `tests/test_migration_integration.py`
against a PostgreSQL test database with PGVector enabled. The test downgrades to
base, upgrades to head, checks `alembic current`, and inspects schema objects:

- `vector` extension exists.
- `filing_chunks.embedding` is `vector(1024)`.
- `ix_filing_chunks_embedding_hnsw` exists.
- `filing_chunks.search_vector` is generated for full-text retrieval.
- `ix_filing_chunks_search_vector_gin` exists.
- Filing, section, table, chunk, and processing-stage tables exist.
- Phase 3 comparison tables exist with review-preserving disclosure fields.

Run the migration suite with:

```bash
RUN_INTEGRATION_TESTS=1 RUN_POSTGRES_TESTS=1 python -m pytest -m "integration and postgres" -q
```

## Retention

- Original SEC filing objects are retained indefinitely for reproducibility unless storage policy changes.
- Analysis results, evidence, reports, and audit events are retained for portfolio/demo reproducibility.
- Failed transient job logs can be compacted after operational metrics are aggregated, but failure state and error category remain attached to the affected entity.

## Managed Local Development

Managed PostgreSQL/PGVector is supported without Docker. The application uses
`DATABASE_URL` with `postgresql+asyncpg`; Alembic uses `ALEMBIC_DATABASE_URL`
with a synchronous driver such as `postgresql+psycopg`; integration tests use
`TEST_DATABASE_URL`.

Destructive migration tests refuse to run when the test URL equals the
application URL, when both URLs point to the same database name, or when the
test database name does not contain `test`.

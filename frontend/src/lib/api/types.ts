export type ApiMeta = {
  request_id?: string | null;
  pagination?: Record<string, unknown> | null;
};

export type ApiEnvelope<T> = {
  data: T;
  meta: ApiMeta;
  error?: ApiErrorPayload | null;
};

export type ApiErrorPayload = {
  code?: string;
  message?: string;
  details?: unknown;
};

export type ApiListParams = {
  limit?: number;
  offset?: number;
  [key: string]: string | number | boolean | null | undefined;
};

export type CompanySummary = {
  id: string;
  cik: string;
  ticker: string | null;
  legal_name: string;
  exchange: string | null;
  industry: string | null;
  fiscal_year_end: string | null;
  is_active: boolean;
  filing_count: number;
  latest_filing_date: string | null;
  latest_report_period: string | null;
  latest_ingestion_status: string | null;
};

export type CompanyDetail = CompanySummary & {
  recent_status_counts: Record<string, number>;
};

export type FilingSummary = {
  id: string;
  company_id: string;
  accession_number: string;
  form_type: string;
  filing_date: string;
  report_period: string | null;
  primary_document: string;
  source_url: string;
  storage_key: string | null;
  content_hash: string | null;
  ingestion_status: string;
  parser_version: string | null;
  raw_metadata: Record<string, unknown>;
};

export type AnalysisCreateResponse = {
  analysis_run_id: string;
  status: string;
  job_id: string;
};

export type AnalysisRun = {
  id: string;
  company_id: string;
  current_filing_id: string;
  comparison_filing_id: string;
  comparison_id: string | null;
  status: string;
  current_node: string | null;
  workflow_version: string;
  graph_version: string;
  requires_human_review: boolean;
  review_gate_reason: Record<string, unknown> | null;
  review_request_id: string | null;
  report_id: string | null;
  progress: AnalysisProgress;
  counts: Record<string, unknown>;
  warnings: string[];
  failure_code: string | null;
  failure_message: string | null;
  failure_node: string | null;
};

export type AnalysisProgress = {
  status: string;
  current_node: string | null;
  completed_nodes: string[];
  progress_percent: number;
};

export type AnalysisWorkflowEvent = {
  id: string;
  analysis_run_id: string;
  event_type: string;
  node_name: string | null;
  attempt_number: number | null;
  event_payload: Record<string, unknown>;
  duration_ms: number | null;
};

export type AnalysisReviewRequest = {
  id: string;
  analysis_run_id: string;
  review_type: string;
  status: string;
  reason: string;
  finding_ids: string[];
  claim_ids: string[];
  verification_ids: string[];
  reviewed_by: string | null;
  review_comment: string | null;
  review_payload: Record<string, unknown> | null;
};

export type AnalysisReport = {
  id: string;
  analysis_run_id: string;
  report_version: string;
  status: string;
  executive_summary: string;
  comparison_summary: Record<string, unknown>;
  disclosure_change_summary: Record<string, unknown>;
  financial_verification_summary: Record<string, unknown>;
  contradiction_summary: Record<string, unknown>;
  high_priority_findings: Record<string, unknown>[];
  limitations: string[];
  evidence_manifest: Record<string, unknown>;
  report_payload: Record<string, unknown>;
  content_hash: string;
};

export type ComparisonSummary = {
  id: string;
  company_id: string;
  current_filing_id: string;
  comparison_filing_id: string;
  status: string;
  comparison_version: string;
  processing_metrics: Record<string, unknown>;
  summary_counts: Record<string, number>;
};

export type DisclosureChange = {
  id: string;
  comparison_id: string;
  section_match_id: string;
  passage_match_id: string | null;
  change_type: string;
  risk_category: string;
  previous_text: string | null;
  current_text: string | null;
  changed_spans: Record<string, unknown>[];
  change_summary: string;
  change_explanation: string;
  materiality_score: number;
  confidence: number;
  detection_method: string;
  supporting_evidence: Record<string, unknown>;
  materiality_components: Record<string, unknown>;
  original_model_output: Record<string, unknown>;
  model_name: string | null;
  model_version: string | null;
  prompt_version: string | null;
  review_status: string;
  review_comment: string | null;
  reviewer_edits: Record<string, unknown>;
};

export type FinancialClaim = {
  id: string;
  filing_id: string;
  comparison_id: string | null;
  disclosure_change_id: string | null;
  source_section_id: string;
  source_passage_id: string | null;
  claim_text: string;
  canonical_metric_name: string | null;
  claim_type: string;
  direction: string | null;
  reported_value: number | string | null;
  reported_unit: string | null;
  reported_change: number | string | null;
  reported_change_unit: string | null;
  comparison_basis: string | null;
  comparison_text: string | null;
  qualifiers: Record<string, unknown>;
  extraction_confidence: number | string;
  extraction_method: string;
  original_model_output: Record<string, unknown>;
  model_name: string | null;
  model_version: string | null;
  prompt_version: string | null;
  review_status: string;
  review_comment: string | null;
  reviewer_edits: Record<string, unknown>;
};

export type ClaimFactCandidate = {
  id: string;
  financial_claim_id: string;
  xbrl_fact_id: string;
  candidate_role: string;
  concept_priority: number;
  concept_match_score: number | string;
  period_match_score: number | string;
  unit_match_score: number | string;
  accession_match_score: number | string;
  frame_match_score: number | string;
  combined_score: number | string;
  selection_status: string;
  rejection_reason: string | null;
};

export type ClaimVerification = {
  id: string;
  financial_claim_id: string;
  current_xbrl_fact_id: string | null;
  comparison_xbrl_fact_id: string | null;
  verification_status: string;
  current_value: number | string | null;
  comparison_value: number | string | null;
  absolute_change: number | string | null;
  percentage_change: number | string | null;
  percentage_point_change: number | string | null;
  reported_change: number | string | null;
  reported_vs_calculated_difference: number | string | null;
  calculation_type: string;
  formula: string;
  calculation_inputs: Record<string, unknown>;
  calculation_output: Record<string, unknown>;
  tolerance_used: number | string | null;
  verification_reason: string;
  confidence: number | string;
  verification_version: string;
};

export type ContradictionFinding = {
  id: string;
  company_id: string;
  comparison_id: string | null;
  financial_claim_id: string | null;
  claim_verification_id: string | null;
  disclosure_change_id: string | null;
  contradiction_type: string;
  status: string;
  risk_category: string | null;
  severity: string;
  confidence: number | string;
  narrative_claim: string | null;
  narrative_direction: string | null;
  measured_direction: string | null;
  reported_value: number | string | null;
  calculated_value: number | string | null;
  calculated_change: number | string | null;
  difference: number | string | null;
  qualifier: string | null;
  finding_title: string;
  finding_summary: string;
  finding_explanation: string;
  limitations: unknown[];
  deterministic_evidence: Record<string, unknown>;
  supporting_evidence: Record<string, unknown>;
  severity_components: Record<string, unknown>;
  confidence_components: Record<string, unknown>;
  detection_method: string;
  rule_ids: string[];
  model_name: string | null;
  model_version: string | null;
  prompt_version: string | null;
  original_model_output: Record<string, unknown> | null;
  review_status: string;
  review_comment: string | null;
  reviewed_by: string | null;
  reviewer_edits: Record<string, unknown>;
};

export type ContradictionEvidence = {
  id: string;
  contradiction_finding_id: string;
  evidence_type: string;
  filing_id: string | null;
  section_id: string | null;
  passage_id: string | null;
  xbrl_fact_id: string | null;
  financial_claim_id: string | null;
  claim_verification_id: string | null;
  disclosure_change_id: string | null;
  derived_metric_id: string | null;
  source_text: string | null;
  source_hash: string | null;
  source_anchor: string | null;
  evidence_role: string;
  metadata: Record<string, unknown>;
};

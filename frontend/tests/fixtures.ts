import type {
  AnalysisReport,
  AnalysisReviewRequest,
  ClaimFactCandidate,
  ClaimVerification,
  CompanySummary,
  ContradictionEvidence,
  ContradictionFinding,
  DisclosureChange,
  FilingSummary,
  FinancialClaim
} from "@/lib/api/types";

export const company: CompanySummary = {
  id: "company-1",
  cik: "0000320193",
  ticker: "AAPL",
  legal_name: "Apple Inc.",
  exchange: "NASDAQ",
  industry: "Technology",
  fiscal_year_end: "0930",
  is_active: true,
  filing_count: 2,
  latest_filing_date: "2024-08-02",
  latest_report_period: "2024-06-29",
  latest_ingestion_status: "processed"
};

export const filings: FilingSummary[] = [
  filing("filing-current", "2024-08-02", "2024-06-29"),
  filing("filing-previous", "2024-05-03", "2024-03-30")
];

export const disclosureChange: DisclosureChange = {
  id: "change-1",
  comparison_id: "comparison-1",
  section_match_id: "section-match-1",
  passage_match_id: "passage-match-1",
  change_type: "weakened",
  risk_category: "liquidity",
  previous_text: "We expect existing cash resources to be sufficient.",
  current_text:
    "We expect existing cash resources and access to external financing to be sufficient, subject to market conditions.",
  changed_spans: [],
  change_summary: "Liquidity language became more conditional.",
  change_explanation: "Added references to external financing and market conditions.",
  materiality_score: 0.82,
  confidence: 0.9,
  detection_method: "deterministic_semantic_diff",
  supporting_evidence: {
    added_phrases: ["access to external financing", "subject to market conditions"]
  },
  materiality_components: {},
  original_model_output: {},
  model_name: null,
  model_version: null,
  prompt_version: null,
  review_status: "pending",
  review_comment: null,
  reviewer_edits: {}
};

export const claim: FinancialClaim = {
  id: "claim-1",
  filing_id: "filing-current",
  comparison_id: "comparison-1",
  disclosure_change_id: null,
  source_section_id: "section-1",
  source_passage_id: "passage-1",
  claim_text: "Revenue increased 12%.",
  canonical_metric_name: "Revenue",
  claim_type: "percentage_change",
  direction: "increase",
  reported_value: null,
  reported_unit: null,
  reported_change: 12,
  reported_change_unit: "percent",
  comparison_basis: "year_over_year",
  comparison_text: null,
  qualifiers: {},
  extraction_confidence: 0.94,
  extraction_method: "deterministic",
  original_model_output: {},
  model_name: null,
  model_version: null,
  prompt_version: null,
  review_status: "pending",
  review_comment: null,
  reviewer_edits: {}
};

export const verification: ClaimVerification = {
  id: "verification-1",
  financial_claim_id: "claim-1",
  current_xbrl_fact_id: "fact-current",
  comparison_xbrl_fact_id: "fact-previous",
  verification_status: "approximately_verified",
  current_value: 111.83,
  comparison_value: 100,
  absolute_change: 11.83,
  percentage_change: 11.83,
  percentage_point_change: null,
  reported_change: 12,
  reported_vs_calculated_difference: 0.17,
  calculation_type: "percentage_change",
  formula: "(current - previous) / previous * 100",
  calculation_inputs: {},
  calculation_output: {},
  tolerance_used: 0.25,
  verification_reason: "Reported change is within configured tolerance.",
  confidence: 0.91,
  verification_version: "phase4"
};

export const factCandidate: ClaimFactCandidate = {
  id: "candidate-1",
  financial_claim_id: "claim-1",
  xbrl_fact_id: "fact-current",
  candidate_role: "current",
  concept_priority: 1,
  concept_match_score: 0.96,
  period_match_score: 1,
  unit_match_score: 1,
  accession_match_score: 1,
  frame_match_score: 0.9,
  combined_score: 0.97,
  selection_status: "selected",
  rejection_reason: null
};

export const finding: ContradictionFinding = {
  id: "finding-1",
  company_id: "company-1",
  comparison_id: "comparison-1",
  financial_claim_id: "claim-1",
  claim_verification_id: "verification-1",
  disclosure_change_id: null,
  contradiction_type: "numerical_claim_contradiction",
  status: "open",
  risk_category: "revenue_margin",
  severity: "high",
  confidence: 0.93,
  narrative_claim: "Revenue increased 12%.",
  narrative_direction: "increase",
  measured_direction: "decrease",
  reported_value: 12,
  calculated_value: -5,
  calculated_change: -5,
  difference: 17,
  qualifier: null,
  finding_title: "Numerical claim differs from official data",
  finding_summary: "The narrative claim and calculated XBRL movement point in different directions.",
  finding_explanation:
    "The claim says revenue increased, but selected official facts calculate a decrease.",
  limitations: ["Ambiguous XBRL fact"],
  deterministic_evidence: {},
  supporting_evidence: {},
  severity_components: {},
  confidence_components: {},
  detection_method: "rule",
  rule_ids: ["REV-DIR-001"],
  model_name: null,
  model_version: null,
  prompt_version: null,
  original_model_output: null,
  review_status: "pending",
  review_comment: null,
  reviewed_by: null,
  reviewer_edits: {}
};

export const evidence: ContradictionEvidence = {
  id: "evidence-1",
  contradiction_finding_id: "finding-1",
  evidence_type: "xbrl_fact",
  filing_id: "filing-current",
  section_id: null,
  passage_id: null,
  xbrl_fact_id: "fact-current",
  financial_claim_id: "claim-1",
  claim_verification_id: "verification-1",
  disclosure_change_id: null,
  derived_metric_id: null,
  source_text: "Revenue increased 12%.",
  source_hash: "abc123",
  source_anchor: "Item 2",
  evidence_role: "supports_calculation",
  metadata: { concept: "Revenue" }
};

export const reviewRequest: AnalysisReviewRequest = {
  id: "review-1",
  analysis_run_id: "analysis-1",
  review_type: "workflow_gate",
  status: "pending",
  reason: "High severity potential inconsistency requires analyst review.",
  finding_ids: ["finding-1"],
  claim_ids: ["claim-1"],
  verification_ids: ["verification-1"],
  reviewed_by: null,
  review_comment: null,
  review_payload: null
};

export const report: AnalysisReport = {
  id: "report-1",
  analysis_run_id: "analysis-1",
  report_version: "phase6",
  status: "completed",
  executive_summary: "One high-priority potential inconsistency requires review.",
  comparison_summary: { company: "AAPL" },
  disclosure_change_summary: { count: 1 },
  financial_verification_summary: { count: 1, approximately_verified: 1 },
  contradiction_summary: { count: 1, high: 1 },
  high_priority_findings: [{ title: "Numerical claim differs from official data" }],
  limitations: ["Ambiguous XBRL fact"],
  evidence_manifest: { items: 1 },
  report_payload: { review_outcomes: { approved: 1, uncertain: 0, rejected: 0 } },
  content_hash: "hash"
};

function filing(id: string, filingDate: string, reportPeriod: string): FilingSummary {
  return {
    id,
    company_id: "company-1",
    accession_number: id,
    form_type: "10-Q",
    filing_date: filingDate,
    report_period: reportPeriod,
    primary_document: "form10q.htm",
    source_url: "https://www.sec.gov/Archives/example",
    storage_key: "filings/example.htm",
    content_hash: "hash",
    ingestion_status: "processed",
    parser_version: "phase2",
    raw_metadata: {}
  };
}

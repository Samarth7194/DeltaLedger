export const workflowStages = [
  "queued",
  "validating",
  "preparing_filings",
  "processing_filings",
  "comparing_disclosures",
  "extracting_claims",
  "verifying_claims",
  "analyzing_contradictions",
  "validating_evidence",
  "awaiting_human_review",
  "generating_report",
  "completed"
];

const labels: Record<string, string> = {
  added: "Added",
  removed: "Removed",
  strengthened: "Strengthened",
  weakened: "Weakened",
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
  edited: "Edited",
  uncertain: "Uncertain",
  partially_approved: "Partially Approved",
  needs_changes: "Needs Changes",
  queued: "Queued",
  running: "Running",
  validate_analysis_request: "Validate Analysis Request",
  ensure_filings_available: "Ensure Filings Available",
  ensure_filings_processed: "Ensure Filings Processed",
  run_disclosure_comparison: "Run Disclosure Comparison",
  extract_financial_claims: "Extract Financial Claims",
  verify_financial_claims: "Verify Financial Claims",
  analyze_contradictions: "Analyze Potential Inconsistencies",
  validate_evidence: "Validate Evidence",
  prioritize_findings: "Prioritize Findings",
  review_gate: "Review Gate",
  generate_report: "Generate Report",
  finalize_analysis: "Finalize Analysis",
  validating: "Validating",
  preparing_filings: "Preparing Filings",
  processing_filings: "Processing Filings",
  comparing_disclosures: "Comparing Disclosures",
  extracting_claims: "Extracting Financial Claims",
  verifying_claims: "Verifying Claims",
  analyzing_contradictions: "Analyzing Potential Inconsistencies",
  validating_evidence: "Validating Evidence",
  creating_comparison: "Creating Comparison",
  matching_sections: "Matching Sections",
  detecting_disclosure_changes: "Detecting Disclosure Changes",
  verifying_financial_claims: "Verifying Financial Claims",
  detecting_contradictions: "Detecting Potential Inconsistencies",
  awaiting_human_review: "Awaiting Human Review",
  generating_report: "Generating Report",
  completed: "Completed",
  completed_with_warnings: "Completed With Warnings",
  failed: "Failed",
  cancelled: "Cancelled",
  verified: "Verified",
  approximately_verified: "Approximately Verified",
  unresolved: "Unresolved",
  contradicted: "Differs From Official Data",
  high: "High",
  medium: "Medium",
  low: "Low",
  numerical_claim_contradiction: "Numerical Claim Differs From Official Data",
  narrative_data_mismatch: "Narrative and Data Differ",
  liquidity: "Liquidity",
  revenue_margin: "Revenue and Margin",
  customer_concentration: "Customer Concentration"
};

export function labelFor(value?: string | null) {
  if (!value) {
    return "Not Available";
  }
  return labels[value] ?? titleize(value);
}

export function statusTone(value?: string | null) {
  if (!value) {
    return "neutral";
  }
  if (["failed", "rejected", "high", "contradicted"].includes(value)) {
    return "danger";
  }
  if (["awaiting_human_review", "needs_changes", "uncertain", "medium"].includes(value)) {
    return "warning";
  }
  if (["completed", "verified", "approved", "low", "processed"].includes(value)) {
    return "success";
  }
  return "neutral";
}

export function isActiveAnalysisStatus(status?: string | null) {
  return Boolean(
    status &&
      !["completed", "completed_with_warnings", "failed", "cancelled", "awaiting_human_review"].includes(
        status
      )
  );
}

export function activeAnalysisRefetchMs(status?: string | null) {
  if (!status) {
    return false;
  }
  if (isActiveAnalysisStatus(status)) {
    return 5_000;
  }
  if (status === "awaiting_human_review") {
    return 30_000;
  }
  return false;
}

function titleize(value: string) {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

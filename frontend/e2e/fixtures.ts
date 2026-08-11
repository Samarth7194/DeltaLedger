import type { Page, Route } from "@playwright/test";

const companyId = "11111111-1111-4111-8111-111111111111";
const currentFilingId = "22222222-2222-4222-8222-222222222222";
const previousFilingId = "33333333-3333-4333-8333-333333333333";
const analysisId = "44444444-4444-4444-8444-444444444444";
const comparisonId = "55555555-5555-4555-8555-555555555555";
const findingId = "66666666-6666-4666-8666-666666666666";
const claimId = "77777777-7777-4777-8777-777777777777";
const reviewId = "88888888-8888-4888-8888-888888888888";

export const ids = {
  companyId,
  currentFilingId,
  previousFilingId,
  analysisId,
  comparisonId,
  findingId,
  claimId,
  reviewId
};

export async function mockDeltaLedgerApi(page: Page) {
  let analysisReadCount = 0;
  let reviewSubmitted = false;
  let resumed = false;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", "");
    const method = request.method();

    if (method === "GET" && path === "/companies") {
      return json(route, [company()]);
    }
    if (method === "GET" && path === `/companies/${companyId}`) {
      return json(route, { ...company(), recent_status_counts: { processed: 2 } });
    }
    if (method === "GET" && path === `/companies/${companyId}/filings`) {
      return json(route, filings());
    }
    if (method === "POST" && path === "/analyses") {
      return json(route, { analysis_run_id: analysisId, status: "queued", job_id: "job-analysis" }, 202);
    }
    if (method === "GET" && path === "/analyses") {
      const status = url.searchParams.get("status");
      if (status === "awaiting_human_review") {
        return json(route, [analysis("awaiting_human_review")]);
      }
      if (status === "completed") {
        return json(route, [analysis("completed")]);
      }
      return json(route, [analysis("awaiting_human_review")]);
    }
    if (method === "GET" && path === `/analyses/${analysisId}`) {
      analysisReadCount += 1;
      const status = resumed
        ? analysisReadCount > 5
          ? "completed"
          : "generating_report"
        : analysisReadCount > 2
          ? "awaiting_human_review"
          : analysisReadCount === 2
            ? "verifying_claims"
            : "comparing_disclosures";
      return json(route, analysis(status));
    }
    if (method === "GET" && path === `/analyses/${analysisId}/events`) {
      return json(route, events());
    }
    if (method === "GET" && path === `/analyses/${analysisId}/review`) {
      return json(route, reviewRequest(reviewSubmitted ? "approved" : "pending"));
    }
    if ((method === "POST" || method === "PATCH") && path === `/analyses/${analysisId}/review`) {
      reviewSubmitted = true;
      return json(route, reviewRequest("approved"));
    }
    if (method === "POST" && path === `/analyses/${analysisId}/resume`) {
      resumed = true;
      analysisReadCount = 3;
      return json(route, {
        analysis_run_id: analysisId,
        review_request_id: reviewId,
        job_id: "job-resume"
      }, 202);
    }
    if (method === "GET" && path === `/analyses/${analysisId}/report`) {
      return json(route, report());
    }
    if (method === "GET" && path === `/comparisons/${comparisonId}/changes`) {
      return json(route, [disclosureChange()]);
    }
    if (method === "GET" && path === `/comparisons/${comparisonId}/financial-claims`) {
      return json(route, [financialClaim()]);
    }
    if (method === "GET" && path === `/comparisons/${comparisonId}/financial-verifications`) {
      return json(route, [verification()]);
    }
    if (method === "GET" && path === `/financial-claims/${claimId}/fact-candidates`) {
      return json(route, [factCandidate()]);
    }
    if (method === "GET" && path === `/comparisons/${comparisonId}/contradictions`) {
      return json(route, [finding()]);
    }
    if (method === "GET" && path === `/contradictions/${findingId}/evidence`) {
      return json(route, [evidence()]);
    }

    return json(route, { message: `Unhandled mock route ${method} ${path}` }, 404);
  });
}

async function json(route: Route, data: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify({ data, meta: { request_id: "req-e2e", pagination: null }, error: null })
  });
}

function company() {
  return {
    id: companyId,
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
}

function filings() {
  return [
    filing(currentFilingId, "2024-08-02", "2024-06-29"),
    filing(previousFilingId, "2024-05-03", "2024-03-30")
  ];
}

function filing(id: string, filingDate: string, reportPeriod: string) {
  return {
    id,
    company_id: companyId,
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

function analysis(status: string) {
  return {
    id: analysisId,
    company_id: companyId,
    current_filing_id: currentFilingId,
    comparison_filing_id: previousFilingId,
    comparison_id: comparisonId,
    status,
    current_node: status === "awaiting_human_review" ? "review_gate" : null,
    workflow_version: "phase6-v1",
    graph_version: "phase6-langgraph-v1",
    requires_human_review: status === "awaiting_human_review",
    review_gate_reason: { reason: "Numerical contradiction candidate requires review." },
    review_request_id: reviewId,
    report_id: status === "completed" ? "report-1" : null,
    progress: {
      status,
      current_node: status === "awaiting_human_review" ? "review_gate" : status,
      completed_nodes: [
        "validate_analysis_request",
        "ensure_filings_available",
        "ensure_filings_processed",
        "run_disclosure_comparison",
        "extract_financial_claims",
        "verify_financial_claims",
        "analyze_contradictions"
      ],
      progress_percent: status === "completed" ? 100 : status === "awaiting_human_review" ? 78 : 55
    },
    counts: {
      disclosure_changes: 1,
      financial_claims: 1,
      verified_claims: 1,
      contradictions: 1
    },
    warnings: [],
    failure_code: null,
    failure_message: null,
    failure_node: null
  };
}

function events() {
  return [
    {
      id: "event-1",
      analysis_run_id: analysisId,
      event_type: "node_completed",
      node_name: "run_disclosure_comparison",
      attempt_number: 1,
      event_payload: { outputs: { disclosure_changes: 1 } },
      duration_ms: 42
    }
  ];
}

function reviewRequest(status: string) {
  return {
    id: reviewId,
    analysis_run_id: analysisId,
    review_type: "contradiction_review",
    status,
    reason: "High severity potential inconsistency requires analyst review.",
    finding_ids: [findingId],
    claim_ids: [claimId],
    verification_ids: ["verification-1"],
    reviewed_by: status === "pending" ? null : "analyst",
    review_comment: status === "pending" ? null : "Approved for report generation.",
    review_payload: status === "pending" ? null : { finding_id: findingId }
  };
}

function disclosureChange() {
  return {
    id: "change-1",
    comparison_id: comparisonId,
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
    detection_method: "hybrid",
    supporting_evidence: { added_phrases: ["access to external financing"] },
    materiality_components: {},
    original_model_output: {},
    model_name: null,
    model_version: null,
    prompt_version: null,
    review_status: "pending",
    review_comment: null,
    reviewer_edits: {}
  };
}

function financialClaim() {
  return {
    id: claimId,
    filing_id: currentFilingId,
    comparison_id: comparisonId,
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
}

function verification() {
  return {
    id: "verification-1",
    financial_claim_id: claimId,
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
    calculation_inputs: { current: 111.83, previous: 100 },
    calculation_output: { result: 11.83 },
    tolerance_used: 0.25,
    verification_reason: "Reported change is within configured tolerance.",
    confidence: 0.91,
    verification_version: "phase4"
  };
}

function factCandidate() {
  return {
    id: "candidate-1",
    financial_claim_id: claimId,
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
}

function finding() {
  return {
    id: findingId,
    company_id: companyId,
    comparison_id: comparisonId,
    financial_claim_id: claimId,
    claim_verification_id: "verification-1",
    disclosure_change_id: null,
    contradiction_type: "numerical_claim_contradiction",
    status: "confirmed_for_review",
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
    finding_explanation: "The claim says revenue increased, but selected official facts calculate a decrease.",
    limitations: ["Ambiguous XBRL fact"],
    deterministic_evidence: {},
    supporting_evidence: {},
    severity_components: {},
    confidence_components: {},
    detection_method: "rule_based",
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
}

function evidence() {
  return {
    id: "evidence-1",
    contradiction_finding_id: findingId,
    evidence_type: "xbrl_fact",
    filing_id: currentFilingId,
    section_id: "section-1",
    passage_id: "passage-1",
    xbrl_fact_id: "fact-current",
    financial_claim_id: claimId,
    claim_verification_id: "verification-1",
    disclosure_change_id: null,
    derived_metric_id: null,
    source_text: "Revenue increased 12%.",
    source_hash: "abc123",
    source_anchor: "Part I Item 2",
    evidence_role: "primary",
    metadata: {
      concept: "RevenueFromContractWithCustomerExcludingAssessedTax",
      value: 111.83,
      unit: "USD",
      period: "2024-Q2",
      accession: currentFilingId,
      formula: "(current - previous) / previous * 100",
      calculation_result: "11.83%"
    }
  };
}

function report() {
  return {
    id: "report-1",
    analysis_run_id: analysisId,
    report_version: "phase6-report-v1",
    status: "finalized",
    executive_summary: "One high-priority potential inconsistency requires review.",
    comparison_summary: { company: "AAPL", current_filing_id: currentFilingId },
    disclosure_change_summary: { count: 1 },
    financial_verification_summary: { count: 1, approximately_verified: 1 },
    contradiction_summary: { count: 1, high: 1 },
    high_priority_findings: [{ title: "Numerical claim differs from official data", evidence_ids: ["evidence-1"] }],
    limitations: ["Ambiguous XBRL fact"],
    evidence_manifest: { evidence_ids: ["evidence-1"], findings: [findingId] },
    report_payload: { review_outcomes: { approved: 1, rejected: 0, uncertain: 0 } },
    content_hash: "hash"
  };
}

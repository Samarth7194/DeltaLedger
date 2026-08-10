import { request } from "@/lib/api/client";
import type {
  AnalysisCreateResponse,
  AnalysisReport,
  AnalysisReviewRequest,
  AnalysisRun,
  AnalysisWorkflowEvent,
  ApiListParams,
  ClaimFactCandidate,
  ClaimVerification,
  CompanyDetail,
  CompanySummary,
  ContradictionEvidence,
  ContradictionFinding,
  DisclosureChange,
  FilingSummary,
  FinancialClaim
} from "@/lib/api/types";

export const api = {
  companies: (params?: ApiListParams) => request<CompanySummary[]>("/companies", { params }),
  company: (companyId: string) => request<CompanyDetail>(`/companies/${companyId}`),
  companyFilings: (companyId: string, params?: ApiListParams) =>
    request<FilingSummary[]>(`/companies/${companyId}/filings`, { params }),
  analyses: (params?: ApiListParams) => request<AnalysisRun[]>("/analyses", { params }),
  analysis: (analysisRunId: string) => request<AnalysisRun>(`/analyses/${analysisRunId}`),
  analysisEvents: (analysisRunId: string, params?: ApiListParams) =>
    request<AnalysisWorkflowEvent[]>(`/analyses/${analysisRunId}/events`, { params }),
  createAnalysis: (body: { current_filing_id: string; comparison_filing_id: string }) =>
    request<AnalysisCreateResponse>("/analyses", {
      method: "POST",
      body: JSON.stringify(body)
    }),
  cancelAnalysis: (analysisRunId: string) =>
    request<AnalysisRun>(`/analyses/${analysisRunId}/cancel`, { method: "POST" }),
  reviewRequest: (analysisRunId: string) =>
    request<AnalysisReviewRequest>(`/analyses/${analysisRunId}/review`),
  submitWorkflowReview: (
    analysisRunId: string,
    body: {
      status: string;
      reviewed_by?: string;
      comment?: string;
      review_payload?: Record<string, unknown>;
    }
  ) =>
    request<AnalysisReviewRequest>(`/analyses/${analysisRunId}/review`, {
      method: "POST",
      body: JSON.stringify(body)
    }),
  resumeAnalysis: (analysisRunId: string) =>
    request<{ analysis_run_id: string; review_request_id: string; job_id: string }>(
      `/analyses/${analysisRunId}/resume`,
      { method: "POST" }
    ),
  report: (analysisRunId: string) =>
    request<AnalysisReport>(`/analyses/${analysisRunId}/report`),
  disclosureChanges: (comparisonId: string, params?: ApiListParams) =>
    request<DisclosureChange[]>(`/comparisons/${comparisonId}/changes`, { params }),
  reviewDisclosureChange: (
    comparisonId: string,
    changeId: string,
    body: { review_status: string; comment?: string; reviewer_id?: string }
  ) =>
    request<DisclosureChange>(`/comparisons/${comparisonId}/changes/${changeId}/review`, {
      method: "PATCH",
      body: JSON.stringify(body)
    }),
  financialClaims: (comparisonId: string, params?: ApiListParams) =>
    request<FinancialClaim[]>(`/comparisons/${comparisonId}/financial-claims`, { params }),
  financialVerifications: (comparisonId: string, params?: ApiListParams) =>
    request<ClaimVerification[]>(`/comparisons/${comparisonId}/financial-verifications`, {
      params
    }),
  factCandidates: (claimId: string) =>
    request<ClaimFactCandidate[]>(`/financial-claims/${claimId}/fact-candidates`),
  reviewFinancialClaim: (
    claimId: string,
    body: { review_status: string; comment?: string; reviewer_id?: string }
  ) =>
    request<FinancialClaim>(`/financial-claims/${claimId}/review`, {
      method: "PATCH",
      body: JSON.stringify(body)
    }),
  contradictions: (comparisonId: string, params?: ApiListParams) =>
    request<ContradictionFinding[]>(`/comparisons/${comparisonId}/contradictions`, { params }),
  contradictionEvidence: (findingId: string) =>
    request<ContradictionEvidence[]>(`/contradictions/${findingId}/evidence`),
  reviewContradiction: (
    findingId: string,
    body: { review_status: string; comment?: string; reviewer_id?: string }
  ) =>
    request<ContradictionFinding>(`/contradictions/${findingId}/review`, {
      method: "PATCH",
      body: JSON.stringify(body)
    })
};

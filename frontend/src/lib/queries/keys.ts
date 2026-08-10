export const queryKeys = {
  companies: (params?: unknown) => ["companies", params] as const,
  company: (companyId: string) => ["company", companyId] as const,
  companyFilings: (companyId: string, params?: unknown) =>
    ["company", companyId, "filings", params] as const,
  analyses: (params?: unknown) => ["analyses", params] as const,
  analysis: (analysisRunId: string) => ["analysis", analysisRunId] as const,
  analysisEvents: (analysisRunId: string) => ["analysis", analysisRunId, "events"] as const,
  reviewRequest: (analysisRunId: string) => ["analysis", analysisRunId, "review"] as const,
  report: (analysisRunId: string) => ["analysis", analysisRunId, "report"] as const,
  disclosureChanges: (comparisonId: string, params?: unknown) =>
    ["comparison", comparisonId, "changes", params] as const,
  financialClaims: (comparisonId: string, params?: unknown) =>
    ["comparison", comparisonId, "financial-claims", params] as const,
  financialVerifications: (comparisonId: string, params?: unknown) =>
    ["comparison", comparisonId, "financial-verifications", params] as const,
  factCandidates: (claimId: string) => ["financial-claim", claimId, "fact-candidates"] as const,
  contradictions: (comparisonId: string, params?: unknown) =>
    ["comparison", comparisonId, "contradictions", params] as const,
  contradictionEvidence: (findingId: string) =>
    ["contradiction", findingId, "evidence"] as const
};

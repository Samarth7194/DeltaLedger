import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/endpoints";
import type { ApiListParams } from "@/lib/api/types";
import { activeAnalysisRefetchMs } from "@/lib/status";

import { queryKeys } from "./keys";

export function useCompanies(params?: ApiListParams) {
  return useQuery({ queryKey: queryKeys.companies(params), queryFn: () => api.companies(params) });
}

export function useCompany(companyId: string) {
  return useQuery({ queryKey: queryKeys.company(companyId), queryFn: () => api.company(companyId) });
}

export function useCompanyFilings(companyId: string, params?: ApiListParams, enabled = true) {
  return useQuery({
    queryKey: queryKeys.companyFilings(companyId, params),
    queryFn: () => api.companyFilings(companyId, params),
    enabled
  });
}

export function useAnalyses(params?: ApiListParams) {
  return useQuery({ queryKey: queryKeys.analyses(params), queryFn: () => api.analyses(params) });
}

export function useAnalysis(analysisRunId: string) {
  return useQuery({
    queryKey: queryKeys.analysis(analysisRunId),
    queryFn: () => api.analysis(analysisRunId),
    refetchInterval: (query) => activeAnalysisRefetchMs(query.state.data?.status)
  });
}

export function useAnalysisEvents(analysisRunId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.analysisEvents(analysisRunId),
    queryFn: () => api.analysisEvents(analysisRunId),
    enabled,
    refetchInterval: 8_000
  });
}

export function useReviewRequest(analysisRunId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.reviewRequest(analysisRunId),
    queryFn: () => api.reviewRequest(analysisRunId),
    enabled,
    retry: false
  });
}

export function useReport(analysisRunId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.report(analysisRunId),
    queryFn: () => api.report(analysisRunId),
    enabled,
    retry: false
  });
}

export function useDisclosureChanges(comparisonId?: string | null, params?: ApiListParams) {
  return useQuery({
    queryKey: queryKeys.disclosureChanges(comparisonId ?? "none", params),
    queryFn: () => api.disclosureChanges(comparisonId as string, params),
    enabled: Boolean(comparisonId)
  });
}

export function useFinancialClaims(comparisonId?: string | null, params?: ApiListParams) {
  return useQuery({
    queryKey: queryKeys.financialClaims(comparisonId ?? "none", params),
    queryFn: () => api.financialClaims(comparisonId as string, params),
    enabled: Boolean(comparisonId)
  });
}

export function useFinancialVerifications(comparisonId?: string | null, params?: ApiListParams) {
  return useQuery({
    queryKey: queryKeys.financialVerifications(comparisonId ?? "none", params),
    queryFn: () => api.financialVerifications(comparisonId as string, params),
    enabled: Boolean(comparisonId)
  });
}

export function useFactCandidates(claimId?: string | null) {
  return useQuery({
    queryKey: queryKeys.factCandidates(claimId ?? "none"),
    queryFn: () => api.factCandidates(claimId as string),
    enabled: Boolean(claimId)
  });
}

export function useContradictions(comparisonId?: string | null, params?: ApiListParams) {
  return useQuery({
    queryKey: queryKeys.contradictions(comparisonId ?? "none", params),
    queryFn: () => api.contradictions(comparisonId as string, params),
    enabled: Boolean(comparisonId)
  });
}

export function useContradictionEvidence(findingId?: string | null) {
  return useQuery({
    queryKey: queryKeys.contradictionEvidence(findingId ?? "none"),
    queryFn: () => api.contradictionEvidence(findingId as string),
    enabled: Boolean(findingId)
  });
}

export function useCreateAnalysis() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.createAnalysis,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["analyses"] })
  });
}

export function useWorkflowReview(analysisRunId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Parameters<typeof api.submitWorkflowReview>[1]) =>
      api.submitWorkflowReview(analysisRunId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.analysis(analysisRunId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.reviewRequest(analysisRunId) });
    }
  });
}

export function useResumeAnalysis(analysisRunId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.resumeAnalysis(analysisRunId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.analysis(analysisRunId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.analysisEvents(analysisRunId) });
    }
  });
}

export function useCancelAnalysis(analysisRunId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelAnalysis(analysisRunId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.analysis(analysisRunId) })
  });
}

export function useFindingReviews(comparisonId?: string | null) {
  const queryClient = useQueryClient();
  return {
    reviewDisclosureChange: useMutation({
      mutationFn: ({
        changeId,
        body
      }: {
        changeId: string;
        body: { review_status: string; comment?: string; reviewer_id?: string };
      }) => api.reviewDisclosureChange(comparisonId as string, changeId, body),
      onSuccess: () =>
        queryClient.invalidateQueries({
          queryKey: queryKeys.disclosureChanges(comparisonId ?? "none")
        })
    }),
    reviewFinancialClaim: useMutation({
      mutationFn: ({
        claimId,
        body
      }: {
        claimId: string;
        body: { review_status: string; comment?: string; reviewer_id?: string };
      }) => api.reviewFinancialClaim(claimId, body),
      onSuccess: () =>
        queryClient.invalidateQueries({
          queryKey: queryKeys.financialClaims(comparisonId ?? "none")
        })
    }),
    reviewContradiction: useMutation({
      mutationFn: ({
        findingId,
        body
      }: {
        findingId: string;
        body: { review_status: string; comment?: string; reviewer_id?: string };
      }) => api.reviewContradiction(findingId, body),
      onSuccess: () =>
        queryClient.invalidateQueries({
          queryKey: queryKeys.contradictions(comparisonId ?? "none")
        })
    })
  };
}

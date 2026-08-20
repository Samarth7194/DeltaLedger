"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { NewAnalysisForm } from "@/components/analyses/new-analysis-form";
import { ErrorState, SkeletonRows } from "@/components/ui/state";
import { useCompanies, useCompanyFilings, useCreateAnalysis } from "@/lib/queries/hooks";

export default function NewAnalysisPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [companyId, setCompanyId] = useState(searchParams.get("companyId") ?? "");
  const companies = useCompanies({ limit: 100 });
  const filings = useCompanyFilings(companyId, { limit: 100, form_type: "10-Q" }, Boolean(companyId));
  const createAnalysis = useCreateAnalysis();

  if (companies.isLoading) {
    return <SkeletonRows rows={6} />;
  }
  if (companies.error || createAnalysis.error) {
    return <ErrorState error={companies.error ?? createAnalysis.error} />;
  }

  return (
    <NewAnalysisForm
      companies={companies.data ?? []}
      filings={filings.data ?? []}
      filingsError={filings.error}
      filingsLoading={filings.isLoading}
      selectedCompanyId={companyId}
      onCompanyChange={setCompanyId}
      submitting={createAnalysis.isPending}
      onSubmit={(current_filing_id, comparison_filing_id) => {
        createAnalysis.mutate(
          { current_filing_id, comparison_filing_id },
          {
            onSuccess: (data) => router.push(`/analyses/${data.analysis_run_id}`)
          }
        );
      }}
    />
  );
}

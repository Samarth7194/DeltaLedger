"use client";

import { GitCompareArrows } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { NewAnalysisForm } from "@/components/analyses/new-analysis-form";
import { PageHeader, SignalPill } from "@/components/ui/product";
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
    <div className="space-y-5">
      <PageHeader
        eyebrow="Comparison setup"
        title="New Analysis"
        description="Build a quarter-over-quarter SEC filing comparison from indexed company data and route it through retrieval, XBRL verification, contradiction checks, and review gates."
        action={<GitCompareArrows aria-hidden="true" className="hidden h-6 w-6 text-ledger-200 sm:block" />}
      >
        <div className="flex flex-wrap gap-2">
          <SignalPill>10-Q filing pairs</SignalPill>
          <SignalPill>Evidence retrieval</SignalPill>
          <SignalPill tone="warning">Human review ready</SignalPill>
        </div>
      </PageHeader>
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
    </div>
  );
}

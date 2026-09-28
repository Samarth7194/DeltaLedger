"use client";

import { ReportListCard } from "@/components/reports/report-list-card";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { PageHeader } from "@/components/ui/product";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/state";
import { useAnalyses } from "@/lib/queries/hooks";

export default function ReportsPage() {
  const analyses = useAnalyses({ status: "completed", limit: 100 });
  const data = analyses.data ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Evidence-backed output"
        title="Reports"
        description="Completed workflow reports collect disclosure changes, claim verification, potential inconsistencies, and review context."
      />
      <Panel>
        <PanelHeader
          title="Completed Analyses"
          eyebrow="Report library"
          detail="Each entry is a generated analyst report: executive summary and high-priority findings, backed by the same evidence trail as the underlying run."
        />
        {analyses.isLoading ? <SkeletonRows rows={6} /> : null}
        {analyses.error ? <ErrorState error={analyses.error} /> : null}
        {!analyses.isLoading && !analyses.error ? (
          data.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {data.map((run) => (
                <ReportListCard key={run.id} run={run} />
              ))}
            </div>
          ) : (
            <EmptyState title="No reports yet" detail="Completed workflow reports appear here." />
          )
        ) : null}
      </Panel>
    </div>
  );
}

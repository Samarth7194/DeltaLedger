"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/state";
import { useAnalyses } from "@/lib/queries/hooks";

export default function ReportsPage() {
  const analyses = useAnalyses({ status: "completed", limit: 100 });

  return (
    <Panel>
      <PanelHeader title="Reports" eyebrow="Completed analyses" />
      {analyses.isLoading ? <SkeletonRows rows={6} /> : null}
      {analyses.error ? <ErrorState error={analyses.error} /> : null}
      {!analyses.isLoading && !analyses.error ? (
        (analyses.data ?? []).length ? (
          <div className="space-y-3">
            {(analyses.data ?? []).map((run) => (
              <Link
                key={run.id}
                href={`/analyses/${run.id}`}
                className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-stone-200 p-4 outline-none hover:bg-stone-50 focus-visible:ring-2 focus-visible:ring-ledger-600"
              >
                <span className="font-semibold">Report for run {run.id.slice(0, 8)}</span>
                <Badge value={run.status} />
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState title="No reports yet" detail="Completed workflow reports appear here." />
        )
      ) : null}
    </Panel>
  );
}

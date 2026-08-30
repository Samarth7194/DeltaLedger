"use client";

import { FileText } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
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
        <PanelHeader title="Completed Analyses" eyebrow="Report library" />
        {analyses.isLoading ? <SkeletonRows rows={6} /> : null}
        {analyses.error ? <ErrorState error={analyses.error} /> : null}
        {!analyses.isLoading && !analyses.error ? (
          data.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {data.map((run) => (
                <Link
                  key={run.id}
                  href={`/analyses/${run.id}`}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-white/10 bg-white/[0.04] p-4 outline-none transition hover:border-ledger-200/30 hover:bg-white/[0.07] focus-visible:ring-2 focus-visible:ring-ledger-500"
                >
                  <span className="inline-flex items-center gap-2 font-semibold text-ink-950">
                    <FileText aria-hidden="true" className="h-4 w-4 text-ledger-200" />
                    Report for run {run.id.slice(0, 8)}
                  </span>
                  <Badge value={run.status} />
                </Link>
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

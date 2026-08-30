"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { PageHeader } from "@/components/ui/product";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/state";
import { useAnalyses } from "@/lib/queries/hooks";

export default function ReviewQueuePage() {
  const analyses = useAnalyses({ status: "awaiting_human_review", limit: 100 });
  const data = analyses.data ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Analyst workstation"
        title="Review Queue"
        description="Inspect workflow runs that require human judgment before findings or reports move forward."
      />
      <Panel>
        <PanelHeader title="Awaiting Human Review" eyebrow="Review gates" />
        {analyses.isLoading ? <SkeletonRows rows={6} /> : null}
        {analyses.error ? <ErrorState error={analyses.error} /> : null}
        {!analyses.isLoading && !analyses.error ? (
          data.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {data.map((run) => (
                <Link
                  key={run.id}
                  href={`/analyses/${run.id}`}
                  className="block rounded-md border border-amber-300/25 bg-amber-400/10 p-4 outline-none transition hover:bg-amber-400/15 focus-visible:ring-2 focus-visible:ring-ledger-500"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="font-mono text-sm font-semibold text-amber-100">Run {run.id.slice(0, 8)}</div>
                      <div className="mt-1 text-sm text-ink-700">
                        {run.current_filing_id.slice(0, 8)} compared with {run.comparison_filing_id.slice(0, 8)}
                      </div>
                    </div>
                    <Badge value={run.status} />
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState title="No review required" detail="There are no workflow runs at a human-review gate." />
          )
        ) : null}
      </Panel>
    </div>
  );
}

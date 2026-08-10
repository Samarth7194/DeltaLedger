"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/state";
import { useAnalyses } from "@/lib/queries/hooks";

export default function ReviewQueuePage() {
  const analyses = useAnalyses({ status: "awaiting_human_review", limit: 100 });

  return (
    <Panel>
      <PanelHeader title="Review Queue" eyebrow="Awaiting human review" />
      {analyses.isLoading ? <SkeletonRows rows={6} /> : null}
      {analyses.error ? <ErrorState error={analyses.error} /> : null}
      {!analyses.isLoading && !analyses.error ? (
        (analyses.data ?? []).length ? (
          <div className="space-y-3">
            {(analyses.data ?? []).map((run) => (
              <Link
                key={run.id}
                href={`/analyses/${run.id}`}
                className="block rounded-md border border-stone-200 p-4 outline-none hover:bg-stone-50 focus-visible:ring-2 focus-visible:ring-ledger-600"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="font-semibold">Run {run.id.slice(0, 8)}</div>
                    <div className="mt-1 text-sm text-stone-600">
                      {run.current_filing_id.slice(0, 8)} compared with{" "}
                      {run.comparison_filing_id.slice(0, 8)}
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
  );
}

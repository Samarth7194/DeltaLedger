"use client";

import { ClipboardCheck } from "lucide-react";

import { ReviewQueueCard } from "@/components/review/review-queue-card";
import { Metric } from "@/components/ui/metric";
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
        description="Runs paused at a review gate, with the potential inconsistencies behind each one surfaced up front so you know what needs judgment before you open it."
      />

      {!analyses.isLoading && !analyses.error ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Metric
            label="Runs Awaiting Review"
            value={data.length}
            detail="Paused at the analyst gate"
            tone={data.length ? "warning" : "success"}
            icon={<ClipboardCheck className="h-4 w-4" />}
          />
          <Metric
            label="Review SLA"
            value="Manual"
            detail="No auto-approval - every run below needs a decision"
          />
        </div>
      ) : null}

      <Panel>
        <PanelHeader
          title="Awaiting Human Review"
          eyebrow="Review gates"
          detail="Sorted by workflow order. Each card previews its highest-severity finding; open a run for full evidence and to approve, reject, or edit."
        />
        {analyses.isLoading ? <SkeletonRows rows={4} /> : null}
        {analyses.error ? <ErrorState error={analyses.error} /> : null}
        {!analyses.isLoading && !analyses.error ? (
          data.length ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {data.map((run) => (
                <ReviewQueueCard key={run.id} run={run} />
              ))}
            </div>
          ) : (
            <EmptyState
              title="No review required"
              detail="There are no workflow runs paused at a human-review gate right now."
            />
          )
        ) : null}
      </Panel>
    </div>
  );
}

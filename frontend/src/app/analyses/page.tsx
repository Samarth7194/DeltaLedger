"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { PageHeader } from "@/components/ui/product";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/state";
import { useAnalyses } from "@/lib/queries/hooks";
import { labelFor } from "@/lib/status";

const statuses = ["", "queued", "running", "awaiting_human_review", "generating_report", "completed", "failed"];

export default function AnalysesPage() {
  const [status, setStatus] = useState("");
  const analyses = useAnalyses({ status, limit: 100 });
  const data = analyses.data ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Analysis runs"
        title="Analyses"
        description="Track filing comparison workflows from request through evidence retrieval, verification, review, and report generation."
        action={
          <Link href="/analyses/new">
            <Button type="button" variant="primary">
              <Plus aria-hidden="true" className="h-4 w-4" />
              New Analysis
            </Button>
          </Link>
        }
      />
      <Panel>
        <PanelHeader title="Workflow Runs" eyebrow="Operations" />
        <label className="mb-4 block max-w-xs text-sm font-medium text-ink-950">
          Status filter
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="mt-2 w-full rounded-md border border-white/12 bg-graphite-950 px-3 py-2 text-ink-950 outline-none focus-visible:ring-2 focus-visible:ring-ledger-500"
          >
            {statuses.map((item) => (
              <option key={item || "all"} value={item}>
                {item ? labelFor(item) : "All statuses"}
              </option>
            ))}
          </select>
        </label>
        {analyses.isLoading ? <SkeletonRows rows={6} /> : null}
        {analyses.error ? <ErrorState error={analyses.error} /> : null}
        {!analyses.isLoading && !analyses.error ? (
          data.length ? (
            <div className="grid gap-3">
              {data.map((run) => (
                <Link
                  key={run.id}
                  href={`/analyses/${run.id}`}
                  className="rounded-md border border-white/10 bg-white/[0.04] p-4 outline-none transition hover:border-ledger-200/30 hover:bg-white/[0.07] focus-visible:ring-2 focus-visible:ring-ledger-500"
                >
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm font-semibold text-ledger-200">{run.id.slice(0, 8)}</span>
                        <Badge value={run.status} />
                      </div>
                      <p className="mt-2 text-sm text-ink-700">
                        Current {run.current_filing_id.slice(0, 8)} compared with previous {run.comparison_filing_id.slice(0, 8)}
                      </p>
                    </div>
                    <div className="min-w-40">
                      <div className="flex justify-between text-xs text-ink-700">
                        <span>Progress</span>
                        <span>{run.progress.progress_percent}%</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded-full bg-white/10">
                        <div className="h-1.5 rounded-full bg-ledger-500" style={{ width: `${Math.max(0, Math.min(100, run.progress.progress_percent))}%` }} />
                      </div>
                    </div>
                    <div className="text-sm text-ink-700">{run.requires_human_review ? "Requires analyst review" : "No review gate"}</div>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState title="No analyses" detail="Create a filing comparison analysis to start." />
          )
        ) : null}
      </Panel>
    </div>
  );
}

"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/state";
import { labelFor } from "@/lib/status";
import { useAnalyses } from "@/lib/queries/hooks";

const statuses = ["", "queued", "running", "awaiting_human_review", "generating_report", "completed", "failed"];

export default function AnalysesPage() {
  const [status, setStatus] = useState("");
  const analyses = useAnalyses({ status, limit: 100 });

  return (
    <Panel>
      <PanelHeader
        title="Analyses"
        eyebrow="Workflow runs"
        action={
          <Link href="/analyses/new">
            <Button type="button" variant="primary">
              <Plus aria-hidden="true" className="h-4 w-4" />
              New Analysis
            </Button>
          </Link>
        }
      />
      <label className="mb-4 block max-w-xs text-sm font-medium">
        Status filter
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="mt-2 w-full rounded-md border border-stone-300 bg-white px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ledger-600"
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
        (analyses.data ?? []).length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-stone-200 text-left text-sm">
              <thead className="bg-stone-50 text-xs uppercase tracking-[0.1em] text-stone-500">
                <tr>
                  <th className="px-3 py-2">Run</th>
                  <th className="px-3 py-2">Current Filing</th>
                  <th className="px-3 py-2">Previous Filing</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Progress</th>
                  <th className="px-3 py-2">Review</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {(analyses.data ?? []).map((run) => (
                  <tr key={run.id}>
                    <td className="px-3 py-3">
                      <Link href={`/analyses/${run.id}`} className="font-medium text-ledger-700">
                        {run.id.slice(0, 8)}
                      </Link>
                    </td>
                    <td className="px-3 py-3 font-mono text-xs">{run.current_filing_id.slice(0, 8)}</td>
                    <td className="px-3 py-3 font-mono text-xs">{run.comparison_filing_id.slice(0, 8)}</td>
                    <td className="px-3 py-3">
                      <Badge value={run.status} />
                    </td>
                    <td className="px-3 py-3">{run.progress.progress_percent}%</td>
                    <td className="px-3 py-3">
                      {run.requires_human_review ? "Requires review" : "No gate"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="No analyses" detail="Create a filing comparison analysis to start." />
        )
      ) : null}
    </Panel>
  );
}

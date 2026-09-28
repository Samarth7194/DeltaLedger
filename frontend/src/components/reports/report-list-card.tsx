"use client";

import { FileText, ShieldAlert } from "lucide-react";
import Link from "next/link";

import type { AnalysisRun } from "@/lib/api/types";
import { useReport } from "@/lib/queries/hooks";

/**
 * One report-library entry. Shows the actual executive summary and
 * high-priority-finding count for runs that have a generated report, so
 * this reads as a list of analyst deliverables rather than bare run links.
 */
export function ReportListCard({ run }: { run: AnalysisRun }) {
  const hasReport = Boolean(run.report_id);
  const report = useReport(run.id, hasReport);
  const findingCount = report.data?.high_priority_findings?.length ?? 0;

  return (
    <Link
      href={`/analyses/${run.id}`}
      className="block rounded-md border border-white/10 bg-white/[0.04] p-4 outline-none transition hover:border-ledger-200/30 hover:bg-white/[0.07] focus-visible:ring-2 focus-visible:ring-ledger-500"
    >
      <div className="flex items-start justify-between gap-3">
        <span className="inline-flex items-center gap-2 font-mono text-sm font-semibold text-ledger-200">
          <FileText aria-hidden="true" className="h-4 w-4 shrink-0" />
          Run {run.id.slice(0, 8)}
        </span>
        {findingCount > 0 ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-amber-300/30 bg-amber-400/10 px-2 py-0.5 text-xs font-medium text-amber-200">
            <ShieldAlert aria-hidden="true" className="h-3 w-3" />
            {findingCount} high-priority
          </span>
        ) : null}
      </div>
      <p className="mt-1.5 text-xs text-ink-700">
        {run.current_filing_id.slice(0, 8)} compared with {run.comparison_filing_id.slice(0, 8)}
      </p>
      {hasReport ? (
        report.isLoading ? (
          <div className="mt-3 h-10 animate-pulse rounded-md bg-white/[0.06]" />
        ) : report.data ? (
          <p className="mt-3 line-clamp-2 text-sm leading-6 text-ink-800">{report.data.executive_summary}</p>
        ) : (
          <p className="mt-3 text-xs text-ink-700">Report summary unavailable.</p>
        )
      ) : (
        <p className="mt-3 text-xs text-ink-700">Report generation has not completed for this run yet.</p>
      )}
    </Link>
  );
}

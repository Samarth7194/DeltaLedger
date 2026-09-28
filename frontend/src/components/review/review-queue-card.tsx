"use client";

import { AlertOctagon, ArrowRight, FileSearch } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AnalysisRun, ContradictionFinding } from "@/lib/api/types";
import { formatConfidence } from "@/lib/formatters";
import { useContradictions } from "@/lib/queries/hooks";
import { labelFor } from "@/lib/status";
import { cn } from "@/lib/utils";

const SEVERITY_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };

function highestSeverityFirst(findings: ContradictionFinding[]) {
  return [...findings].sort((a, b) => {
    const rank = (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0);
    if (rank !== 0) return rank;
    return Number(b.confidence ?? 0) - Number(a.confidence ?? 0);
  });
}

/**
 * One analyst-facing review card for a run awaiting human review. Pulls its
 * own potential-inconsistency findings (via the run's comparison_id) so the
 * queue can surface severity, confidence, and evidence state up front,
 * instead of making the analyst open every run to find out what's inside.
 */
export function ReviewQueueCard({ run }: { run: AnalysisRun }) {
  const contradictions = useContradictions(run.comparison_id, { limit: 100 });
  const findings = useMemo(() => contradictions.data ?? [], [contradictions.data]);
  const ordered = useMemo(() => highestSeverityFirst(findings), [findings]);
  const topFinding = ordered[0];
  const severityCounts = useMemo(() => {
    const counts: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 };
    for (const finding of findings) {
      if (finding.severity in counts) counts[finding.severity] += 1;
    }
    return counts;
  }, [findings]);
  const pendingCount = findings.filter((finding) => finding.review_status === "pending").length;

  return (
    <Link
      href={`/analyses/${run.id}`}
      className="group block rounded-md border border-white/10 bg-white/[0.04] p-4 outline-none transition hover:border-amber-300/30 hover:bg-white/[0.07] focus-visible:ring-2 focus-visible:ring-ledger-500"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-semibold text-ledger-200">Run {run.id.slice(0, 8)}</span>
            <Badge value="awaiting_human_review" />
          </div>
          <p className="mt-1.5 text-xs text-ink-700">
            Filing {run.current_filing_id.slice(0, 8)} vs. {run.comparison_filing_id.slice(0, 8)}
          </p>
        </div>
        <ArrowRight
          aria-hidden="true"
          className="h-4 w-4 shrink-0 text-ink-700 transition group-hover:translate-x-0.5 group-hover:text-amber-200"
        />
      </div>

      {contradictions.isLoading ? (
        <div className="mt-3 h-14 animate-pulse rounded-md bg-white/[0.06]" />
      ) : !run.comparison_id || findings.length === 0 ? (
        <p className="mt-3 text-xs text-ink-700">
          {run.review_gate_reason && typeof run.review_gate_reason.reason === "string"
            ? run.review_gate_reason.reason
            : "Awaiting analyst decision. No potential inconsistencies were flagged for this run."}
        </p>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {(["critical", "high", "medium", "low"] as const)
              .filter((severity) => severityCounts[severity] > 0)
              .map((severity) => (
                <span
                  key={severity}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium",
                    severity === "critical" && "border-red-300/40 bg-red-500/15 text-red-100",
                    severity === "high" && "border-red-300/30 bg-red-400/10 text-red-200",
                    severity === "medium" && "border-amber-300/30 bg-amber-400/10 text-amber-200",
                    severity === "low" && "border-white/10 bg-white/[0.06] text-ink-800"
                  )}
                >
                  {severity === "critical" ? <AlertOctagon aria-hidden="true" className="h-3 w-3" /> : null}
                  {severityCounts[severity]} {labelFor(severity)}
                </span>
              ))}
            <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 text-xs text-ink-700">
              {pendingCount} of {findings.length} pending
            </span>
          </div>

          {topFinding ? (
            <div className="mt-3 rounded-md border border-white/10 bg-graphite-950/60 p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="line-clamp-1 text-sm font-medium text-ink-950">{topFinding.finding_title}</p>
                <span className="shrink-0 text-xs text-ink-700">{formatConfidence(topFinding.confidence)}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-xs text-ink-700">{topFinding.finding_summary}</p>
            </div>
          ) : null}
        </>
      )}

      <div className="mt-3 flex justify-end">
        <Button type="button" variant="secondary" className="pointer-events-none text-xs">
          <FileSearch aria-hidden="true" className="h-3.5 w-3.5" />
          Open for Review
        </Button>
      </div>
    </Link>
  );
}

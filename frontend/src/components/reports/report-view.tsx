"use client";

import { Download, Printer } from "lucide-react";

import type { AnalysisReport } from "@/lib/api/types";
import { compactJson } from "@/lib/formatters";

import { Button } from "../ui/button";
import { Metric } from "../ui/metric";
import { EmptyState } from "../ui/state";

export function ReportView({ report }: { report?: AnalysisReport }) {
  if (!report) {
    return (
      <EmptyState
        title="No final report yet"
        detail="Reports appear after the workflow passes review and completes report generation."
      />
    );
  }

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `deltaledger-report-${report.analysis_run_id}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <article className="space-y-5 rounded-md border border-stone-200 bg-white p-5 print:border-0 print:p-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
            DeltaLedger Analysis
          </p>
          <h2 className="text-2xl font-semibold">Structured Report</h2>
          <p className="mt-1 text-sm text-stone-600">Version {report.report_version}</p>
        </div>
        <div className="flex gap-2 no-print">
          <Button type="button" onClick={() => window.print()}>
            <Printer aria-hidden="true" className="h-4 w-4" />
            Print
          </Button>
          <Button type="button" onClick={downloadJson}>
            <Download aria-hidden="true" className="h-4 w-4" />
            JSON
          </Button>
        </div>
      </div>

      <section>
        <h3 className="text-base font-semibold">Executive Summary</h3>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-stone-700">
          {report.executive_summary}
        </p>
      </section>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric
          label="Disclosure Changes"
          value={countFrom(report.disclosure_change_summary)}
          detail="Material changes and review states"
        />
        <Metric
          label="Financial Claims"
          value={countFrom(report.financial_verification_summary)}
          detail="Claims checked against official data"
        />
        <Metric
          label="Potential Inconsistencies"
          value={countFrom(report.contradiction_summary)}
          detail="Requires evidence review"
        />
        <Metric label="High Priority" value={report.high_priority_findings.length} detail="Top findings" />
      </section>

      <ReportSection title="Disclosure Changes" value={report.disclosure_change_summary} />
      <ReportSection title="Financial Verification Summary" value={report.financial_verification_summary} />
      <ReportSection title="Potential Inconsistencies" value={report.contradiction_summary} />
      <ReportFindings findings={report.high_priority_findings} />
      <ReportSection title="Review Outcomes" value={reviewOutcomes(report.report_payload)} />
      <section className="rounded-md border border-amber-200 bg-amberline-100 p-4">
        <h3 className="text-base font-semibold text-amber-950">Limitations</h3>
        {report.limitations.length ? (
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-950">
            {report.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-amber-900">No report limitations were returned.</p>
        )}
      </section>
      <ReportSection title="Evidence Manifest" value={report.evidence_manifest} />
    </article>
  );
}

function ReportSection({ title, value }: { title: string; value: Record<string, unknown> }) {
  return (
    <section className="rounded-md border border-stone-200 p-4">
      <h3 className="text-base font-semibold">{title}</h3>
      <pre className="mt-3 max-h-72 overflow-auto rounded-md bg-stone-950 p-3 text-xs text-stone-50">
        {compactJson(value)}
      </pre>
    </section>
  );
}

function ReportFindings({ findings }: { findings: Record<string, unknown>[] }) {
  return (
    <section className="rounded-md border border-stone-200 p-4">
      <h3 className="text-base font-semibold">High-Priority Findings</h3>
      {findings.length ? (
        <div className="mt-3 space-y-3">
          {findings.map((finding, index) => (
            <pre key={index} className="overflow-auto rounded-md bg-stone-950 p-3 text-xs text-stone-50">
              {compactJson(finding)}
            </pre>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-sm text-stone-600">No high-priority findings were returned.</p>
      )}
    </section>
  );
}

function countFrom(value: Record<string, unknown>) {
  const count = value.count ?? value.total ?? value.total_count;
  return typeof count === "number" ? count : "N/A";
}

function reviewOutcomes(payload: Record<string, unknown>) {
  const value = payload.review_outcomes;
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : { status: "No review outcomes returned." };
}

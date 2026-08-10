"use client";

import { AlertTriangle, CheckCircle2, Clock3, FolderSearch } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Metric } from "@/components/ui/metric";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/state";
import { formatDate } from "@/lib/formatters";
import { useAnalyses, useCompanies } from "@/lib/queries/hooks";

export default function DashboardPage() {
  const analyses = useAnalyses({ limit: 8 });
  const companies = useCompanies({ limit: 6 });

  if (analyses.isLoading || companies.isLoading) {
    return <SkeletonRows rows={6} />;
  }
  if (analyses.error || companies.error) {
    return <ErrorState error={analyses.error ?? companies.error} />;
  }

  const runs = analyses.data ?? [];
  const awaiting = runs.filter((run) => run.status === "awaiting_human_review");
  const completed = runs.filter((run) => run.status === "completed" || run.status === "completed_with_warnings");
  const failed = runs.filter((run) => run.status === "failed" || run.status === "cancelled");
  const inconsistencyCount = runs.reduce((total, run) => total + numericCount(run.counts.contradictions), 0);

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric label="Recent Analyses" value={runs.length} detail="Latest workflow runs" />
        <Metric label="Awaiting Review" value={awaiting.length} detail="Human review gates" />
        <Metric label="Completed" value={completed.length} detail="Reports ready or nearly ready" />
        <Metric label="Potential Inconsistencies" value={inconsistencyCount} detail="Across recent runs" />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel>
          <PanelHeader
            title="Recent Analyses"
            eyebrow="Workflow"
            action={
              <Link href="/analyses/new">
                <Button type="button" variant="primary">
                  <FolderSearch aria-hidden="true" className="h-4 w-4" />
                  New Analysis
                </Button>
              </Link>
            }
          />
          {runs.length ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-stone-200 text-left text-sm">
                <thead className="bg-stone-50 text-xs uppercase tracking-[0.1em] text-stone-500">
                  <tr>
                    <th className="px-3 py-2">Analysis</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Progress</th>
                    <th className="px-3 py-2">Review</th>
                    <th className="px-3 py-2">Warnings</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-100">
                  {runs.map((run) => (
                    <tr key={run.id}>
                      <td className="px-3 py-3">
                        <Link href={`/analyses/${run.id}`} className="font-medium text-ledger-700">
                          {run.id.slice(0, 8)}
                        </Link>
                      </td>
                      <td className="px-3 py-3">
                        <Badge value={run.status} />
                      </td>
                      <td className="px-3 py-3">{run.progress.progress_percent}%</td>
                      <td className="px-3 py-3">
                        {run.requires_human_review ? (
                          <span className="inline-flex items-center gap-1 text-amber-700">
                            <Clock3 aria-hidden="true" className="h-4 w-4" />
                            Required
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-emerald-700">
                            <CheckCircle2 aria-hidden="true" className="h-4 w-4" />
                            Clear
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-3">{run.warnings.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No analyses yet" detail="Create an analysis from two processed 10-Q filings." />
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Recent Companies" eyebrow="Coverage" />
          {(companies.data ?? []).length ? (
            <div className="space-y-3">
              {(companies.data ?? []).map((company) => (
                <Link
                  key={company.id}
                  href={`/companies/${company.id}`}
                  className="block rounded-md border border-stone-200 p-3 outline-none hover:bg-stone-50 focus-visible:ring-2 focus-visible:ring-ledger-600"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-semibold">{company.ticker ?? company.cik}</div>
                    <Badge value={company.latest_ingestion_status} />
                  </div>
                  <p className="mt-1 text-sm text-stone-600">{company.legal_name}</p>
                  <p className="mt-2 text-xs text-stone-500">
                    Latest report {formatDate(company.latest_report_period)}
                  </p>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState title="No companies" detail="Ingest SEC company metadata to begin analysis." />
          )}
        </Panel>
      </div>

      {failed.length ? (
        <Panel className="border-red-200 bg-red-50">
          <div className="flex items-start gap-3">
            <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5 text-red-700" />
            <div>
              <h2 className="font-semibold text-red-950">Failures or cancellations require attention</h2>
              <p className="mt-1 text-sm text-red-900">
                {failed.length} recent workflow run returned a failed or cancelled state.
              </p>
            </div>
          </div>
        </Panel>
      ) : null}
    </div>
  );
}

function numericCount(value: unknown) {
  return typeof value === "number" ? value : 0;
}

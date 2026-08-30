"use client";

import { PlayCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { FilingTable } from "@/components/filings/filing-table";
import { Badge } from "@/components/ui/badge";
import { Metric } from "@/components/ui/metric";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { PageHeader, SignalPill } from "@/components/ui/product";
import { ErrorState, SkeletonRows } from "@/components/ui/state";
import { formatDate } from "@/lib/formatters";
import { useAnalyses, useCompany, useCompanyFilings } from "@/lib/queries/hooks";

export default function CompanyDetailPage() {
  const params = useParams<{ companyId: string }>();
  const companyId = stringParam(params.companyId);
  const company = useCompany(companyId);
  const filings = useCompanyFilings(companyId, { limit: 50, form_type: "10-Q" });
  const analyses = useAnalyses({ company_id: companyId, limit: 8 });

  if (company.isLoading || filings.isLoading || analyses.isLoading) {
    return <SkeletonRows rows={6} />;
  }
  if (company.error || filings.error || analyses.error) {
    return <ErrorState error={company.error ?? filings.error ?? analyses.error} />;
  }

  const detail = company.data;
  if (!detail) {
    return <ErrorState error={new Error("Company not found.")} />;
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Company monitor"
        title={detail.ticker ?? detail.cik}
        description={detail.legal_name}
        action={
          <Link href={`/analyses/new?companyId=${detail.id}`}>
            <button className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-ledger-500 bg-ledger-500 px-3 py-2 text-sm font-medium text-graphite-980 transition hover:bg-ledger-200 focus-visible:ring-2 focus-visible:ring-ledger-500" type="button">
              <PlayCircle aria-hidden="true" className="h-4 w-4" />
              New Analysis
            </button>
          </Link>
        }
      >
        <div className="flex flex-wrap gap-2">
          <SignalPill>CIK {detail.cik}</SignalPill>
          {detail.exchange ? <SignalPill>{detail.exchange}</SignalPill> : null}
          {detail.industry ? <SignalPill>{detail.industry}</SignalPill> : null}
          <Badge value={detail.latest_ingestion_status} />
        </div>
      </PageHeader>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric label="Filings" value={detail.filing_count} detail="Stored SEC filings" />
        <Metric label="Latest Period" value={formatDate(detail.latest_report_period)} />
        <Metric label="Latest Filing" value={formatDate(detail.latest_filing_date)} />
        <Metric label="Active" value={detail.is_active ? "Yes" : "No"} tone={detail.is_active ? "success" : "warning"} />
      </div>

      <Panel>
        <PanelHeader title="Filings" eyebrow="10-Q selection" detail="Available filings for inspection and comparison workflows." />
        <FilingTable filings={filings.data ?? []} />
      </Panel>

      <Panel>
        <PanelHeader title="Recent Analyses" eyebrow="History" />
        {(analyses.data ?? []).length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {(analyses.data ?? []).map((run) => (
              <Link
                key={run.id}
                href={`/analyses/${run.id}`}
                className="rounded-md border border-white/10 bg-white/[0.04] p-3 outline-none transition hover:border-ledger-200/30 hover:bg-white/[0.07] focus-visible:ring-2 focus-visible:ring-ledger-500"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="font-mono text-sm font-medium text-ledger-200">{run.id.slice(0, 8)}</span>
                  <Badge value={run.status} />
                </div>
                <p className="mt-2 text-xs text-ink-700">Progress {run.progress.progress_percent}%</p>
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-sm text-ink-700">No analyses have been created for this company yet.</p>
        )}
      </Panel>
    </div>
  );
}

function stringParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : (value ?? "");
}

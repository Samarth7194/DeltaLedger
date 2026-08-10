"use client";

import { PlayCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { FilingTable } from "@/components/filings/filing-table";
import { Badge } from "@/components/ui/badge";
import { Metric } from "@/components/ui/metric";
import { Panel, PanelHeader } from "@/components/ui/panel";
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
      <Panel>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
              Company
            </p>
            <h2 className="text-2xl font-semibold">{detail.ticker ?? detail.cik}</h2>
            <p className="mt-1 text-sm text-stone-600">{detail.legal_name}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge value={detail.latest_ingestion_status} />
              <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1 text-xs">
                CIK {detail.cik}
              </span>
              {detail.exchange ? (
                <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1 text-xs">
                  {detail.exchange}
                </span>
              ) : null}
            </div>
          </div>
          <Link
            href={`/analyses/new?companyId=${detail.id}`}
            className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-ledger-700 bg-ledger-700 px-3 py-2 text-sm font-medium text-white outline-none transition hover:bg-ledger-600 focus-visible:ring-2 focus-visible:ring-ledger-600"
          >
            <PlayCircle aria-hidden="true" className="h-4 w-4" />
            New Analysis
          </Link>
        </div>
      </Panel>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric label="Filings" value={detail.filing_count} detail="Stored filings" />
        <Metric label="Latest Period" value={formatDate(detail.latest_report_period)} />
        <Metric label="Latest Filing" value={formatDate(detail.latest_filing_date)} />
        <Metric label="Industry" value={detail.industry ?? "Not available"} />
      </div>

      <Panel>
        <PanelHeader title="Filings" eyebrow="10-Q selection" />
        <FilingTable filings={filings.data ?? []} />
      </Panel>

      <Panel>
        <PanelHeader title="Recent Analyses" eyebrow="History" />
        {(analyses.data ?? []).length ? (
          <div className="space-y-2">
            {(analyses.data ?? []).map((run) => (
              <Link
                key={run.id}
                href={`/analyses/${run.id}`}
                className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-stone-200 p-3 outline-none hover:bg-stone-50 focus-visible:ring-2 focus-visible:ring-ledger-600"
              >
                <span className="font-medium">{run.id.slice(0, 8)}</span>
                <Badge value={run.status} />
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-sm text-stone-600">No analyses have been created for this company yet.</p>
        )}
      </Panel>
    </div>
  );
}

function stringParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : (value ?? "");
}

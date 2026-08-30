"use client";

import { ArrowRight, Building2, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { DataRow, PageHeader } from "@/components/ui/product";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/state";
import { formatDate } from "@/lib/formatters";
import { useCompanies } from "@/lib/queries/hooks";

export default function CompaniesPage() {
  const [search, setSearch] = useState("");
  const companies = useCompanies({ search, limit: 100 });
  const data = companies.data ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Coverage"
        title="Companies"
        description="Monitor SEC registrants, filing freshness, and available filing history before launching a comparison."
      >
        <label className="flex max-w-xl items-center gap-2 rounded-md border border-white/10 bg-graphite-950/80 px-3 py-2 text-sm shadow-panel">
          <Search aria-hidden="true" className="h-4 w-4 text-ledger-200" />
          <span className="sr-only">Search companies</span>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search ticker, CIK, or company name"
            className="w-full bg-transparent text-ink-950 outline-none placeholder:text-ink-700"
          />
        </label>
      </PageHeader>

      {companies.isLoading ? <SkeletonRows rows={6} /> : null}
      {companies.error ? <ErrorState error={companies.error} /> : null}
      {!companies.isLoading && !companies.error ? (
        data.length ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {data.map((company) => (
              <Panel key={company.id} className="group transition hover:border-ledger-200/30 hover:bg-graphite-850/90">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2 text-xs uppercase text-ledger-200/85">
                      <Building2 aria-hidden="true" className="h-3.5 w-3.5" />
                      {company.ticker ?? "SEC registrant"}
                    </div>
                    <h2 className="mt-2 text-lg font-semibold text-ink-950">{company.legal_name}</h2>
                  </div>
                  <Badge value={company.latest_ingestion_status} />
                </div>

                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                  <DataRow label="CIK" value={<span className="font-mono text-xs">{company.cik}</span>} />
                  <DataRow label="Filings" value={company.filing_count} />
                  <DataRow label="Latest Period" value={formatDate(company.latest_report_period)} />
                  <DataRow label="Industry" value={company.industry ?? "Not available"} />
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <Link href={`/companies/${company.id}`} className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-white/12 bg-white/[0.06] px-3 py-2 text-sm font-medium text-ink-950 transition hover:bg-white/[0.1] focus-visible:ring-2 focus-visible:ring-ledger-500">
                    Inspect
                    <ArrowRight aria-hidden="true" className="h-4 w-4" />
                  </Link>
                  <Link href={`/analyses/new?companyId=${company.id}`}>
                    <Button type="button" variant="primary">Start Analysis</Button>
                  </Link>
                </div>
              </Panel>
            ))}
          </div>
        ) : (
          <EmptyState title="No companies indexed" detail="SEC company data has not yet been ingested for this environment." />
        )
      ) : null}
    </div>
  );
}

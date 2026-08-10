"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/state";
import { formatDate } from "@/lib/formatters";
import { useCompanies } from "@/lib/queries/hooks";

export default function CompaniesPage() {
  const [search, setSearch] = useState("");
  const companies = useCompanies({ search, limit: 100 });

  return (
    <Panel>
      <PanelHeader title="Companies" eyebrow="Coverage" />
      <label className="mb-4 flex max-w-lg items-center gap-2 rounded-md border border-stone-300 bg-white px-3 py-2 text-sm">
        <Search aria-hidden="true" className="h-4 w-4 text-stone-500" />
        <span className="sr-only">Search companies</span>
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search ticker, CIK, or company name"
          className="w-full outline-none"
        />
      </label>
      {companies.isLoading ? <SkeletonRows rows={6} /> : null}
      {companies.error ? <ErrorState error={companies.error} /> : null}
      {!companies.isLoading && !companies.error ? (
        (companies.data ?? []).length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-stone-200 text-left text-sm">
              <thead className="bg-stone-50 text-xs uppercase tracking-[0.1em] text-stone-500">
                <tr>
                  <th className="px-3 py-2">Company</th>
                  <th className="px-3 py-2">CIK</th>
                  <th className="px-3 py-2">Industry</th>
                  <th className="px-3 py-2">Filings</th>
                  <th className="px-3 py-2">Latest Period</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {(companies.data ?? []).map((company) => (
                  <tr key={company.id}>
                    <td className="px-3 py-3">
                      <Link href={`/companies/${company.id}`} className="font-medium text-ledger-700">
                        {company.ticker ?? company.legal_name}
                      </Link>
                      <div className="text-xs text-stone-500">{company.legal_name}</div>
                    </td>
                    <td className="px-3 py-3 font-mono text-xs">{company.cik}</td>
                    <td className="px-3 py-3">{company.industry ?? "Not available"}</td>
                    <td className="px-3 py-3">{company.filing_count}</td>
                    <td className="px-3 py-3">{formatDate(company.latest_report_period)}</td>
                    <td className="px-3 py-3">
                      <Badge value={company.latest_ingestion_status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="No companies" detail="No company records matched the current search." />
        )
      ) : null}
    </Panel>
  );
}

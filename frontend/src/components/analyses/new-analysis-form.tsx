"use client";

import { ArrowRight, Building2, CheckCircle2, PlayCircle } from "lucide-react";
import { useMemo, useState } from "react";

import type { CompanySummary, FilingSummary } from "@/lib/api/types";
import { formatDate } from "@/lib/formatters";

import { FilingTable } from "../filings/filing-table";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Panel, PanelHeader } from "../ui/panel";
import { DataRow } from "../ui/product";
import { EmptyState, ErrorState, SkeletonRows } from "../ui/state";

export function isValidFilingPair(
  current?: FilingSummary,
  comparison?: FilingSummary
): boolean {
  if (!current || !comparison || current.id === comparison.id) {
    return false;
  }
  const currentPeriod = current.report_period ?? current.filing_date;
  const comparisonPeriod = comparison.report_period ?? comparison.filing_date;
  return new Date(currentPeriod) > new Date(comparisonPeriod);
}

export function NewAnalysisForm({
  companies,
  filings,
  filingsError,
  filingsLoading = false,
  selectedCompanyId,
  onCompanyChange,
  onSubmit,
  submitting = false
}: {
  companies: CompanySummary[];
  filings: FilingSummary[];
  filingsError?: unknown;
  filingsLoading?: boolean;
  selectedCompanyId?: string;
  onCompanyChange: (companyId: string) => void;
  onSubmit: (currentFilingId: string, comparisonFilingId: string) => void;
  submitting?: boolean;
}) {
  const [currentId, setCurrentId] = useState("");
  const [comparisonId, setComparisonId] = useState("");
  const selectedCompany = useMemo(
    () => companies.find((company) => company.id === selectedCompanyId),
    [companies, selectedCompanyId]
  );
  const current = useMemo(() => filings.find((filing) => filing.id === currentId), [filings, currentId]);
  const comparison = useMemo(
    () => filings.find((filing) => filing.id === comparisonId),
    [filings, comparisonId]
  );
  const validPair = isValidFilingPair(current, comparison);

  return (
    <div className="grid gap-4 xl:grid-cols-[380px_minmax(0,1fr)]">
      <Panel>
        <PanelHeader
          title="Create Analysis"
          eyebrow="Guided workflow"
          detail="Choose an issuer, select an earlier filing, then select a later filing for evidence-backed comparison."
        />
        <ol className="mb-5 grid gap-2 text-sm">
          <Step label="Select Company" active={!selectedCompanyId} done={Boolean(selectedCompanyId)} />
          <Step label="Select Earlier Filing" active={Boolean(selectedCompanyId) && !comparisonId} done={Boolean(comparisonId)} />
          <Step label="Select Later Filing" active={Boolean(comparisonId) && !currentId} done={Boolean(currentId)} />
          <Step label="Review Comparison" active={Boolean(currentId && comparisonId)} done={validPair} />
        </ol>

        <label className="text-sm font-medium text-ink-950" htmlFor="company">
          Company
        </label>
        <select
          id="company"
          value={selectedCompanyId ?? ""}
          onChange={(event) => {
            setCurrentId("");
            setComparisonId("");
            onCompanyChange(event.target.value);
          }}
          className="mt-2 w-full rounded-md border border-white/12 bg-graphite-950 px-3 py-2 text-sm text-ink-950 outline-none focus-visible:ring-2 focus-visible:ring-ledger-500"
        >
          <option value="">Select company</option>
          {companies.map((company) => (
            <option key={company.id} value={company.id}>
              {company.ticker ?? company.cik} - {company.legal_name}
            </option>
          ))}
        </select>

        {selectedCompany ? (
          <div className="mt-4 rounded-md border border-white/10 bg-white/[0.04] p-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink-950">
              <Building2 aria-hidden="true" className="h-4 w-4 text-ledger-200" />
              {selectedCompany.ticker ?? selectedCompany.legal_name}
            </div>
            <p className="mt-1 text-sm text-ink-700">{selectedCompany.legal_name}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge value={selectedCompany.latest_ingestion_status} />
              <span className="rounded-md border border-white/10 bg-white/[0.05] px-2 py-1 text-xs text-ink-700">
                {selectedCompany.filing_count} filings
              </span>
            </div>
          </div>
        ) : null}

        <div className="mt-5 space-y-3 rounded-md border border-white/10 bg-white/[0.04] p-3 text-sm">
          <div className="font-medium text-ink-950">Filing pair rule</div>
          <p className="text-ink-700">The later filing must have a newer report period than the earlier filing.</p>
          <div className="flex items-center gap-2 text-xs text-ink-700">
            <span>Earlier</span>
            <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
            <span>Later</span>
          </div>
        </div>

        <div className="mt-5 grid gap-2">
          <DataRow label="Earlier Filing" value={comparison ? filingLabel(comparison) : "Not selected"} />
          <DataRow label="Later Filing" value={current ? filingLabel(current) : "Not selected"} />
        </div>

        <Button
          className="mt-5 w-full"
          disabled={!validPair || submitting}
          onClick={() => currentId && comparisonId && onSubmit(currentId, comparisonId)}
          type="button"
          variant="primary"
        >
          <PlayCircle aria-hidden="true" className="h-4 w-4" />
          {submitting ? "Creating Analysis" : "Create Analysis"}
        </Button>
        {!validPair && currentId && comparisonId ? (
          <p className="mt-3 text-sm text-amber-200">Select a later filing with a newer report period than the earlier filing.</p>
        ) : null}
      </Panel>

      <Panel>
        <PanelHeader title="Available Filings" eyebrow="Selection" detail="Use the filing cards to choose an earlier baseline and later current period." />
        {selectedCompanyId ? (
          filingsLoading ? (
            <SkeletonRows rows={4} />
          ) : filingsError ? (
            <ErrorState error={filingsError} />
          ) : (
            <FilingTable
              filings={filings}
              currentId={currentId}
              comparisonId={comparisonId}
              onSelectCurrent={setCurrentId}
              onSelectComparison={setComparisonId}
            />
          )
        ) : (
          <EmptyState title="Select a company" detail="Filing choices appear after a company is selected." />
        )}
      </Panel>
    </div>
  );
}

function Step({ label, active, done }: { label: string; active: boolean; done: boolean }) {
  return (
    <li className="flex items-center gap-2 rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-ink-700">
      {done ? <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-emerald-200" /> : <span className="h-2 w-2 rounded-full bg-ledger-200" />}
      <span className={active ? "text-ink-950" : undefined}>{label}</span>
    </li>
  );
}

function filingLabel(filing: FilingSummary) {
  return `${filing.form_type} ${formatDate(filing.report_period)} filed ${formatDate(filing.filing_date)}`;
}

"use client";

import { ArrowRight, PlayCircle } from "lucide-react";
import { useMemo, useState } from "react";

import type { CompanySummary, FilingSummary } from "@/lib/api/types";

import { FilingTable } from "../filings/filing-table";
import { Button } from "../ui/button";
import { Panel, PanelHeader } from "../ui/panel";
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
  const current = useMemo(() => filings.find((filing) => filing.id === currentId), [filings, currentId]);
  const comparison = useMemo(
    () => filings.find((filing) => filing.id === comparisonId),
    [filings, comparisonId]
  );
  const validPair = isValidFilingPair(current, comparison);

  return (
    <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
      <Panel>
        <PanelHeader title="Create Analysis" eyebrow="New comparison" />
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
          className="mt-2 w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ledger-600"
        >
          <option value="">Select company</option>
          {companies.map((company) => (
            <option key={company.id} value={company.id}>
              {company.ticker ?? company.cik} - {company.legal_name}
            </option>
          ))}
        </select>

        <div className="mt-5 space-y-3 rounded-md border border-stone-200 bg-stone-50 p-3 text-sm">
          <div className="font-medium">Filing pair rule</div>
          <p className="text-stone-600">
            Current filing must be later than the comparison filing and from the same company.
          </p>
          <div className="flex items-center gap-2 text-xs text-stone-600">
            <span>Previous</span>
            <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
            <span>Current</span>
          </div>
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
          <p className="mt-3 text-sm text-amber-700">
            Select a current filing with a later report period than the previous filing.
          </p>
        ) : null}
      </Panel>

      <Panel>
        <PanelHeader title="Available Filings" eyebrow="Selection" />
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

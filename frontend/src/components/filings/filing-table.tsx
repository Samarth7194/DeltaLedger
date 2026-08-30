"use client";

import { CheckCircle2 } from "lucide-react";

import type { FilingSummary } from "@/lib/api/types";
import { formatDate } from "@/lib/formatters";
import { cn } from "@/lib/utils";

import { Badge } from "../ui/badge";
import { EmptyState } from "../ui/state";

export function FilingTable({
  filings,
  currentId,
  comparisonId,
  onSelectCurrent,
  onSelectComparison
}: {
  filings: FilingSummary[];
  currentId?: string;
  comparisonId?: string;
  onSelectCurrent?: (id: string) => void;
  onSelectComparison?: (id: string) => void;
}) {
  if (filings.length === 0) {
    return (
      <EmptyState
        title="No filings found"
        detail="Ingest company filings first, then return here to create a comparison."
      />
    );
  }

  return (
    <div className="grid gap-3">
      {filings.map((filing) => {
        const isCurrent = filing.id === currentId;
        const isComparison = filing.id === comparisonId;
        return (
          <article
            key={filing.id}
            className={cn(
              "rounded-md border border-white/10 bg-white/[0.04] p-4 transition hover:border-ledger-200/30 hover:bg-white/[0.07]",
              (isCurrent || isComparison) && "border-ledger-200/40 bg-ledger-500/10"
            )}
          >
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge value={filing.ingestion_status} />
                  <span className="rounded-md border border-white/10 bg-white/[0.05] px-2 py-1 text-xs font-medium text-ink-800">
                    {filing.form_type}
                  </span>
                </div>
                <h3 className="mt-3 text-base font-semibold text-ink-950">Report period {formatDate(filing.report_period)}</h3>
                <p className="mt-1 text-sm text-ink-700">Filed {formatDate(filing.filing_date)}</p>
                <p className="mt-2 break-all font-mono text-xs text-ink-700">{filing.accession_number}</p>
              </div>
              {(onSelectCurrent || onSelectComparison) && (
                <div className="flex flex-wrap gap-2 lg:justify-end">
                  {onSelectComparison ? (
                    <SelectionButton selected={isComparison} label="Previous" onClick={() => onSelectComparison(filing.id)} />
                  ) : null}
                  {onSelectCurrent ? (
                    <SelectionButton selected={isCurrent} label="Current" onClick={() => onSelectCurrent(filing.id)} />
                  ) : null}
                </div>
              )}
            </div>
          </article>
        );
      })}
    </div>
  );
}

function SelectionButton({
  selected,
  label,
  onClick
}: {
  selected: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex min-h-9 items-center gap-1 rounded-md border px-3 py-2 text-xs font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-ledger-500",
        selected
          ? "border-ledger-200/40 bg-ledger-500/15 text-ledger-100"
          : "border-white/12 bg-white/[0.06] text-ink-900 hover:bg-white/[0.1]"
      )}
    >
      {selected ? <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5 text-ledger-200" /> : null}
      {label}
    </button>
  );
}

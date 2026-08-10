"use client";

import { CheckCircle2 } from "lucide-react";

import type { FilingSummary } from "@/lib/api/types";
import { formatDate } from "@/lib/formatters";

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
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-stone-200 text-left text-sm">
        <thead className="bg-stone-50 text-xs uppercase tracking-[0.1em] text-stone-500">
          <tr>
            <th className="px-3 py-2">Form</th>
            <th className="px-3 py-2">Report Period</th>
            <th className="px-3 py-2">Filed</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Accession</th>
            {(onSelectCurrent || onSelectComparison) && <th className="px-3 py-2">Use As</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-stone-100">
          {filings.map((filing) => {
            const isCurrent = filing.id === currentId;
            const isComparison = filing.id === comparisonId;
            return (
              <tr key={filing.id} className="bg-white align-top">
                <td className="px-3 py-3 font-medium">{filing.form_type}</td>
                <td className="px-3 py-3">{formatDate(filing.report_period)}</td>
                <td className="px-3 py-3">{formatDate(filing.filing_date)}</td>
                <td className="px-3 py-3">
                  <Badge value={filing.ingestion_status} />
                </td>
                <td className="max-w-56 px-3 py-3 font-mono text-xs text-stone-600">
                  {filing.accession_number}
                </td>
                {(onSelectCurrent || onSelectComparison) && (
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-2">
                      {onSelectCurrent ? (
                        <SelectionButton
                          selected={isCurrent}
                          label="Current"
                          onClick={() => onSelectCurrent(filing.id)}
                        />
                      ) : null}
                      {onSelectComparison ? (
                        <SelectionButton
                          selected={isComparison}
                          label="Previous"
                          onClick={() => onSelectComparison(filing.id)}
                        />
                      ) : null}
                    </div>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
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
      className="inline-flex items-center gap-1 rounded-md border border-stone-300 bg-white px-2 py-1 text-xs font-medium outline-none hover:bg-stone-100 focus-visible:ring-2 focus-visible:ring-ledger-600"
    >
      {selected ? <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5 text-ledger-700" /> : null}
      {label}
    </button>
  );
}

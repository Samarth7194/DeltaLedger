"use client";

import { SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";

import type { DisclosureChange } from "@/lib/api/types";
import { formatConfidence, formatPercent } from "@/lib/formatters";
import { labelFor } from "@/lib/status";

import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { EmptyState } from "../ui/state";

export function DisclosureChangeList({ changes }: { changes: DisclosureChange[] }) {
  const [selectedId, setSelectedId] = useState(changes[0]?.id ?? "");
  const selected = useMemo(
    () => changes.find((change) => change.id === selectedId) ?? changes[0],
    [changes, selectedId]
  );

  if (changes.length === 0) {
    return (
      <EmptyState
        title="No disclosure changes found"
        detail="When comparisons complete, material narrative changes appear here."
      />
    );
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm font-medium text-stone-700">
          <SlidersHorizontal aria-hidden="true" className="h-4 w-4" />
          Disclosure Changes
        </div>
        {changes.map((change) => (
          <button
            key={change.id}
            type="button"
            onClick={() => setSelectedId(change.id)}
            className="w-full rounded-md border border-stone-200 bg-white p-3 text-left outline-none hover:bg-stone-50 focus-visible:ring-2 focus-visible:ring-ledger-600"
          >
            <div className="flex flex-wrap gap-2">
              <Badge value={change.change_type} />
              <Badge value={change.risk_category} />
              <Badge value={change.review_status} />
            </div>
            <h3 className="mt-2 text-sm font-semibold">{change.change_summary}</h3>
            <p className="mt-1 text-xs text-stone-600">
              Materiality {formatPercent(change.materiality_score)} ·{" "}
              {formatConfidence(change.confidence)}
            </p>
          </button>
        ))}
      </div>
      {selected ? <DisclosureSideBySide change={selected} /> : null}
    </div>
  );
}

export function DisclosureSideBySide({ change }: { change: DisclosureChange }) {
  return (
    <article className="rounded-md border border-stone-200 bg-white p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge value={change.change_type} />
        <Badge value={change.risk_category} />
        <span className="text-sm text-stone-600">{labelFor(change.detection_method)}</span>
      </div>
      <h3 className="text-base font-semibold">{change.change_summary}</h3>
      <p className="mt-2 text-sm text-stone-700">{change.change_explanation}</p>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <EvidenceText label="Previous" text={change.previous_text} />
        <EvidenceText label="Current" text={change.current_text} />
      </div>
      <details className="mt-4 rounded-md border border-stone-200 p-3">
        <summary className="cursor-pointer text-sm font-medium">Structured supporting evidence</summary>
        <pre className="mt-3 max-h-56 overflow-auto rounded-md bg-stone-950 p-3 text-xs text-stone-50">
          {JSON.stringify(change.supporting_evidence, null, 2)}
        </pre>
      </details>
      <div className="mt-4 flex flex-wrap gap-2 no-print">
        {["approved", "rejected", "uncertain"].map((status) => (
          <Button key={status} type="button" variant="secondary">
            {labelFor(status)}
          </Button>
        ))}
      </div>
    </article>
  );
}

function EvidenceText({ label, text }: { label: string; text?: string | null }) {
  return (
    <section className="rounded-md border border-stone-200 bg-stone-50 p-3">
      <h4 className="text-sm font-semibold">{label}</h4>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-stone-800">
        {text ?? "No text returned for this side of the comparison."}
      </p>
    </section>
  );
}

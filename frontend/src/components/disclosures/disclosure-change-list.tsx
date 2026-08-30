"use client";

import { SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";

import type { DisclosureChange } from "@/lib/api/types";
import { formatConfidence, formatPercent } from "@/lib/formatters";
import { labelFor } from "@/lib/status";
import { cn } from "@/lib/utils";

import { Badge } from "../ui/badge";
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
        <div className="flex items-center gap-2 text-sm font-medium text-ink-800">
          <SlidersHorizontal aria-hidden="true" className="h-4 w-4 text-ledger-200" />
          Disclosure changes
        </div>
        {changes.map((change) => (
          <button
            key={change.id}
            type="button"
            onClick={() => setSelectedId(change.id)}
            className={cn(
              "w-full rounded-md border p-3 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-ledger-500",
              selected?.id === change.id
                ? "border-ledger-200/40 bg-ledger-500/10"
                : "border-white/10 bg-white/[0.04] hover:border-ledger-200/30 hover:bg-white/[0.07]"
            )}
          >
            <div className="flex flex-wrap gap-2">
              <Badge value={change.change_type} />
              <Badge value={change.risk_category} />
              <Badge value={change.review_status} />
            </div>
            <h3 className="mt-2 text-sm font-semibold text-ink-950">{change.change_summary}</h3>
            <p className="mt-1 text-xs text-ink-700">
              Materiality {formatPercent(change.materiality_score)} - {formatConfidence(change.confidence)}
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
    <article className="rounded-md border border-white/10 bg-white/[0.04] p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge value={change.change_type} />
        <Badge value={change.risk_category} />
        <span className="text-sm text-ink-700">{labelFor(change.detection_method)}</span>
      </div>
      <h3 className="text-base font-semibold text-ink-950">{change.change_summary}</h3>
      <p className="mt-2 text-sm leading-6 text-ink-700">{change.change_explanation}</p>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <EvidenceText label="Previous" text={change.previous_text} />
        <EvidenceText label="Current" text={change.current_text} />
      </div>
      <details className="mt-4 rounded-md border border-white/10 bg-graphite-950/60 p-3">
        <summary className="cursor-pointer text-sm font-medium text-ink-950">Structured supporting evidence</summary>
        <pre className="mt-3 max-h-56 overflow-auto rounded-md bg-graphite-950 p-3 text-xs text-ink-900">
          {JSON.stringify(change.supporting_evidence, null, 2)}
        </pre>
      </details>
    </article>
  );
}

function EvidenceText({ label, text }: { label: string; text?: string | null }) {
  return (
    <section className="rounded-md border border-white/10 bg-graphite-950/60 p-3">
      <h4 className="text-sm font-semibold text-ink-950">{label}</h4>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-ink-800">
        {text ?? "No text returned for this side of the comparison."}
      </p>
    </section>
  );
}

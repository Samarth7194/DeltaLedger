"use client";

import { FileSearch } from "lucide-react";
import { useMemo, useState } from "react";

import type { ContradictionFinding } from "@/lib/api/types";
import { formatConfidence, formatNumber } from "@/lib/formatters";
import { labelFor } from "@/lib/status";

import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { EmptyState } from "../ui/state";

export function InconsistencyList({
  findings,
  onOpenEvidence
}: {
  findings: ContradictionFinding[];
  onOpenEvidence?: (findingId: string) => void;
}) {
  const [selectedId, setSelectedId] = useState(findings[0]?.id ?? "");
  const selected = useMemo(
    () => findings.find((finding) => finding.id === selectedId) ?? findings[0],
    [findings, selectedId]
  );

  if (findings.length === 0) {
    return (
      <EmptyState
        title="No potential inconsistencies detected"
        detail="This analysis did not return contradiction candidates requiring inspection."
      />
    );
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
      <div className="space-y-2">
        {findings.map((finding) => (
          <button
            key={finding.id}
            type="button"
            onClick={() => setSelectedId(finding.id)}
            className="w-full rounded-md border border-stone-200 bg-white p-3 text-left outline-none hover:bg-stone-50 focus-visible:ring-2 focus-visible:ring-ledger-600"
          >
            <div className="flex flex-wrap gap-2">
              <Badge value={finding.severity} />
              <Badge value={finding.review_status} />
            </div>
            <h3 className="mt-2 text-sm font-semibold">{finding.finding_title}</h3>
            <p className="mt-1 line-clamp-3 text-xs text-stone-600">{finding.finding_summary}</p>
          </button>
        ))}
      </div>
      {selected ? <InconsistencyDetail finding={selected} onOpenEvidence={onOpenEvidence} /> : null}
    </div>
  );
}

export function InconsistencyDetail({
  finding,
  onOpenEvidence
}: {
  finding: ContradictionFinding;
  onOpenEvidence?: (findingId: string) => void;
}) {
  return (
    <article className="rounded-md border border-stone-200 bg-white p-4">
      <div className="flex flex-wrap gap-2">
        <Badge value={finding.contradiction_type} />
        <Badge value={finding.severity} />
        <Badge value={finding.risk_category} />
      </div>
      <h3 className="mt-3 text-base font-semibold">{finding.finding_title}</h3>
      <p className="mt-2 text-sm leading-6 text-stone-700">{finding.finding_explanation}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <DiffTerm label="Narrative Direction" value={labelFor(finding.narrative_direction)} />
        <DiffTerm label="Measured Direction" value={labelFor(finding.measured_direction)} />
        <DiffTerm label="Reported" value={formatNumber(finding.reported_value)} />
        <DiffTerm label="Calculated" value={formatNumber(finding.calculated_value)} />
      </div>
      <div className="mt-4 rounded-md border border-amber-200 bg-amberline-100 p-3 text-sm text-amber-900">
        <strong>Potential Inconsistency.</strong> This finding indicates that narrative language and
        official data may differ. It requires human review before publication.
      </div>
      <dl className="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-stone-500">
            Confidence
          </dt>
          <dd className="mt-1">{formatConfidence(finding.confidence)}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-stone-500">
            Rule IDs
          </dt>
          <dd className="mt-1">{finding.rule_ids.join(", ") || "Not available"}</dd>
        </div>
      </dl>
      {finding.limitations.length ? (
        <section className="mt-4">
          <h4 className="text-sm font-semibold">Limitations</h4>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-stone-700">
            {finding.limitations.map((limitation, index) => (
              <li key={index}>{String(limitation)}</li>
            ))}
          </ul>
        </section>
      ) : null}
      <div className="mt-4 flex flex-wrap gap-2 no-print">
        <Button type="button" onClick={() => onOpenEvidence?.(finding.id)}>
          <FileSearch aria-hidden="true" className="h-4 w-4" />
          Open Evidence
        </Button>
      </div>
    </article>
  );
}

function DiffTerm({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-stone-200 bg-stone-50 p-3">
      <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-stone-500">{label}</dt>
      <dd className="mt-1 text-sm font-semibold">{value}</dd>
    </div>
  );
}

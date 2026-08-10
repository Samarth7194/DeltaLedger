"use client";

import { FileSearch, X } from "lucide-react";

import type { ContradictionEvidence } from "@/lib/api/types";
import { compactJson } from "@/lib/formatters";
import { labelFor } from "@/lib/status";

import { Button } from "../ui/button";
import { EmptyState, SkeletonRows } from "../ui/state";

export function EvidenceViewer({
  title = "Available Evidence",
  open,
  loading,
  evidence,
  onClose
}: {
  title?: string;
  open: boolean;
  loading?: boolean;
  evidence?: ContradictionEvidence[];
  onClose: () => void;
}) {
  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label={title}>
      <button
        type="button"
        aria-label="Close evidence viewer"
        className="absolute inset-0 bg-ink-950/35"
        onClick={onClose}
      />
      <aside className="absolute right-0 top-0 h-full w-full max-w-2xl overflow-y-auto bg-white p-5 shadow-xl sm:p-6">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
              Evidence
            </p>
            <h2 className="text-lg font-semibold">{title}</h2>
          </div>
          <Button type="button" variant="ghost" onClick={onClose} aria-label="Close">
            <X aria-hidden="true" className="h-4 w-4" />
          </Button>
        </div>
        {loading ? <SkeletonRows rows={4} /> : <EvidenceList evidence={evidence ?? []} />}
      </aside>
    </div>
  );
}

export function EvidenceList({ evidence }: { evidence: ContradictionEvidence[] }) {
  if (evidence.length === 0) {
    return (
      <EmptyState
        title="No evidence rows returned"
        detail="The finding can still include structured supporting evidence in its detail fields."
      />
    );
  }
  return (
    <div className="space-y-3">
      {evidence.map((item) => (
        <article key={item.id} className="rounded-md border border-stone-200 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <FileSearch aria-hidden="true" className="h-4 w-4 text-ledger-700" />
            <span className="text-sm font-semibold">{labelFor(item.evidence_type)}</span>
            <span className="text-xs text-stone-500">{labelFor(item.evidence_role)}</span>
          </div>
          {item.source_text ? (
            <blockquote className="mt-3 rounded-md bg-stone-50 p-3 text-sm text-stone-800">
              {item.source_text}
            </blockquote>
          ) : null}
          <dl className="mt-3 grid gap-2 text-xs text-stone-600 sm:grid-cols-2">
            <div>
              <dt className="font-semibold">Source Anchor</dt>
              <dd>{item.source_anchor ?? "Not available"}</dd>
            </div>
            <div>
              <dt className="font-semibold">Source Hash</dt>
              <dd className="font-mono">{item.source_hash ?? "Not available"}</dd>
            </div>
          </dl>
          <pre className="mt-3 max-h-40 overflow-auto rounded-md bg-stone-950 p-3 text-xs text-stone-50">
            {compactJson(item.metadata)}
          </pre>
        </article>
      ))}
    </div>
  );
}

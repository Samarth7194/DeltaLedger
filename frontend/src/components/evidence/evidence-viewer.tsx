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
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />
      <aside className="absolute right-0 top-0 h-full w-full max-w-2xl overflow-y-auto border-l border-white/10 bg-graphite-950 p-5 shadow-2xl sm:p-6">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase text-ledger-200">Evidence</p>
            <h2 className="text-lg font-semibold text-ink-950">{title}</h2>
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
        <article key={item.id} className="rounded-md border border-white/10 bg-white/[0.04] p-3">
          <div className="flex flex-wrap items-center gap-2">
            <FileSearch aria-hidden="true" className="h-4 w-4 text-ledger-200" />
            <span className="text-sm font-semibold text-ink-950">{labelFor(item.evidence_type)}</span>
            <span className="text-xs text-ink-700">{labelFor(item.evidence_role)}</span>
          </div>
          {item.source_text ? (
            <blockquote className="mt-3 rounded-md border border-white/10 bg-graphite-900 p-3 text-sm text-ink-800">
              {item.source_text}
            </blockquote>
          ) : null}
          <dl className="mt-3 grid gap-2 text-xs text-ink-700 sm:grid-cols-2">
            <div>
              <dt className="font-semibold text-ink-950">Source Anchor</dt>
              <dd>{item.source_anchor ?? "Not available"}</dd>
            </div>
            <div>
              <dt className="font-semibold text-ink-950">Source Hash</dt>
              <dd className="break-all font-mono">{item.source_hash ?? "Not available"}</dd>
            </div>
          </dl>
          <pre className="mt-3 max-h-40 overflow-auto rounded-md bg-graphite-950 p-3 text-xs text-ink-900">
            {compactJson(item.metadata)}
          </pre>
        </article>
      ))}
    </div>
  );
}

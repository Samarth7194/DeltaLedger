import { AlertCircle, Inbox } from "lucide-react";

import { ApiError } from "@/lib/api/client";

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-md border border-dashed border-white/15 bg-white/[0.04] p-6 text-center">
      <Inbox aria-hidden="true" className="mx-auto mb-2 h-5 w-5 text-ledger-200" />
      <h3 className="text-sm font-semibold text-ink-950">{title}</h3>
      <p className="mt-1 text-sm text-ink-700">{detail}</p>
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : "The backend did not return a usable response.";
  return (
    <div className="rounded-md border border-red-300/25 bg-red-500/10 p-4 text-red-100">
      <div className="flex items-start gap-2">
        <AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <h3 className="text-sm font-semibold">Unable to load this workspace</h3>
          <p className="mt-1 text-sm text-red-100/80">{message}</p>
        </div>
      </div>
    </div>
  );
}

export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-label="Loading content">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="h-12 animate-pulse rounded-md bg-white/[0.08]" />
      ))}
    </div>
  );
}

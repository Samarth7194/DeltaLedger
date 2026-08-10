import { AlertCircle, Inbox } from "lucide-react";

import { ApiError } from "@/lib/api/client";

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-md border border-dashed border-stone-300 bg-stone-50 p-6 text-center">
      <Inbox aria-hidden="true" className="mx-auto mb-2 h-5 w-5 text-stone-500" />
      <h3 className="text-sm font-semibold text-ink-950">{title}</h3>
      <p className="mt-1 text-sm text-stone-600">{detail}</p>
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
    <div className="rounded-md border border-red-200 bg-red-50 p-4 text-red-900">
      <div className="flex items-start gap-2">
        <AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4" />
        <div>
          <h3 className="text-sm font-semibold">Unable to load this workspace</h3>
          <p className="mt-1 text-sm">{message}</p>
        </div>
      </div>
    </div>
  );
}

export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-label="Loading content">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="h-12 animate-pulse rounded-md bg-stone-200" />
      ))}
    </div>
  );
}

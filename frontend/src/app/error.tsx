"use client";

import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <Panel className="mx-auto max-w-2xl">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-1 h-5 w-5 text-red-700" aria-hidden="true" />
        <div className="space-y-3">
          <div>
            <h1 className="text-lg font-semibold text-ink-950">Unable to load this view</h1>
            <p className="mt-1 text-sm text-stone-600">
              The request failed safely. Try again or check the backend readiness status.
            </p>
          </div>
          {error.digest ? (
            <p className="text-xs text-stone-500">Reference: {error.digest}</p>
          ) : null}
          <Button onClick={reset} variant="primary">
            Retry
          </Button>
        </div>
      </div>
    </Panel>
  );
}

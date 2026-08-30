import type { AnalysisWorkflowEvent } from "@/lib/api/types";
import { labelFor } from "@/lib/status";

import { EmptyState } from "../ui/state";

export function WorkflowEvents({ events }: { events: AnalysisWorkflowEvent[] }) {
  if (events.length === 0) {
    return <EmptyState title="No workflow events yet" detail="Events appear as the analysis advances." />;
  }
  return (
    <div className="max-h-[520px] overflow-y-auto pr-1">
      <ol className="space-y-3">
        {events.map((event) => (
          <li key={event.id} className="rounded-md border border-white/10 bg-white/[0.04] p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-medium text-ink-950">{labelFor(event.event_type)}</div>
              {event.duration_ms ? (
                <div className="text-xs text-ink-700">{event.duration_ms} ms</div>
              ) : null}
            </div>
            <div className="mt-1 text-sm text-ink-700">{labelFor(event.node_name)}</div>
            <pre className="mt-2 max-h-28 overflow-auto rounded-md bg-graphite-950 p-2 text-xs text-ink-900">
              {JSON.stringify(event.event_payload, null, 2)}
            </pre>
          </li>
        ))}
      </ol>
    </div>
  );
}

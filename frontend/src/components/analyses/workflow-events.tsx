import type { AnalysisWorkflowEvent } from "@/lib/api/types";
import { labelFor } from "@/lib/status";

import { EmptyState } from "../ui/state";

export function WorkflowEvents({ events }: { events: AnalysisWorkflowEvent[] }) {
  if (events.length === 0) {
    return <EmptyState title="No workflow events yet" detail="Events appear as the analysis advances." />;
  }
  return (
    <div className="max-h-[520px] overflow-y-auto">
      <ol className="space-y-3">
        {events.map((event) => (
          <li key={event.id} className="rounded-md border border-stone-200 bg-white p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-medium">{labelFor(event.event_type)}</div>
              {event.duration_ms ? (
                <div className="text-xs text-stone-500">{event.duration_ms} ms</div>
              ) : null}
            </div>
            <div className="mt-1 text-sm text-stone-600">{labelFor(event.node_name)}</div>
            <pre className="mt-2 max-h-28 overflow-auto rounded-md bg-stone-950 p-2 text-xs text-stone-50">
              {JSON.stringify(event.event_payload, null, 2)}
            </pre>
          </li>
        ))}
      </ol>
    </div>
  );
}

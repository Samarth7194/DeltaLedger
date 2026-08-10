import { CheckCircle2, Circle, CircleDot, XCircle } from "lucide-react";

import type { AnalysisProgress } from "@/lib/api/types";
import { labelFor, workflowStages } from "@/lib/status";
import { cn } from "@/lib/utils";

import { Badge } from "../ui/badge";

export function WorkflowProgress({ progress }: { progress: AnalysisProgress }) {
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <Badge value={progress.status} />
        <span className="text-sm font-medium text-stone-700">{progress.progress_percent}%</span>
      </div>
      <div className="h-2 rounded-full bg-stone-200">
        <div
          className="h-2 rounded-full bg-ledger-700 transition-all"
          style={{ width: `${Math.max(0, Math.min(100, progress.progress_percent))}%` }}
        />
      </div>
      <ol className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {workflowStages.map((stage) => {
          const complete = progress.completed_nodes.includes(stage) || progress.status === "completed";
          const current = progress.current_node === stage || progress.status === stage;
          const failed = progress.status === "failed" && progress.current_node === stage;
          const Icon = failed ? XCircle : complete ? CheckCircle2 : current ? CircleDot : Circle;
          return (
            <li
              key={stage}
              className={cn(
                "flex min-h-10 items-center gap-2 rounded-md border px-3 py-2 text-sm",
                complete && "border-emerald-200 bg-emerald-50",
                current && "border-ledger-700 bg-ledger-100",
                failed && "border-red-200 bg-red-50",
                !complete && !current && !failed && "border-stone-200 bg-stone-50"
              )}
            >
              <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />
              <span>{labelFor(stage)}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

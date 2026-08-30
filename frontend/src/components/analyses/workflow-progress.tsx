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
        <span className="text-sm font-semibold text-ink-950">{progress.progress_percent}%</span>
      </div>
      <div className="h-2 rounded-full bg-white/10">
        <div
          className="h-2 rounded-full bg-ledger-500 shadow-glow transition-all"
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
                "flex min-h-10 items-center gap-2 rounded-md border px-3 py-2 text-sm text-ink-800",
                complete && "border-emerald-300/25 bg-emerald-400/10 text-emerald-100",
                current && "border-ledger-200/35 bg-ledger-500/12 text-ledger-100",
                failed && "border-red-300/25 bg-red-500/10 text-red-100",
                !complete && !current && !failed && "border-white/10 bg-white/[0.04]"
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

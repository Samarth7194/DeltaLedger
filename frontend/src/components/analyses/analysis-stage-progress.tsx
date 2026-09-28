import { AlertTriangle, CheckCircle2, Circle, CircleDot, PauseCircle, XCircle } from "lucide-react";

import type {
  AnalysisProgress,
  AnalysisStagePart,
  AnalysisStageProgress as StageProgress
} from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { providerPauseMessage } from "./analysis-recovery";

const number = new Intl.NumberFormat("en-US");

function fmt(value?: number | null) {
  return value === null || value === undefined ? "—" : number.format(value);
}

type Presentation = {
  icon: typeof Circle;
  label: string;
  row: string;
  text: string;
};

function present(stage: StageProgress): Presentation {
  switch (stage.status) {
    case "completed":
      return {
        icon: CheckCircle2,
        label: "Completed",
        row: "border-emerald-300/25 bg-emerald-400/10",
        text: "text-emerald-200"
      };
    case "requires_review":
      return {
        icon: AlertTriangle,
        label: "Completed with items to review",
        row: "border-amber-300/30 bg-amber-400/10",
        text: "text-amber-200"
      };
    case "processing":
      return {
        icon: CircleDot,
        label: "Processing",
        row: "border-ledger-200/35 bg-ledger-500/12",
        text: "text-ledger-100"
      };
    case "failed":
      return stage.retryable
        ? {
            icon: PauseCircle,
            label: "Paused – can resume",
            row: "border-amber-300/30 bg-amber-400/10",
            text: "text-amber-200"
          }
        : {
            icon: XCircle,
            label: "Failed",
            row: "border-red-300/25 bg-red-500/10",
            text: "text-red-200"
          };
    default:
      return { icon: Circle, label: "Pending", row: "border-white/10 bg-white/[0.04]", text: "text-ink-700" };
  }
}

function partTone(status: string) {
  if (status === "completed") return "bg-emerald-400/70";
  if (status === "processing") return "bg-ledger-500 animate-pulse";
  if (status === "failed") return "bg-amber-400/80";
  return "bg-white/15";
}

function PartsStrip({ stage, parts }: { stage: string; parts: AnalysisStagePart[] }) {
  return (
    <div className="mt-2 flex flex-wrap gap-1" role="img" aria-label={`${stage} parts`}>
      {parts.map((part) => (
        <span
          key={part.index}
          title={`Part ${part.index}: ${part.status}`}
          className={cn("h-2 w-4 rounded-sm", partTone(part.status))}
        />
      ))}
    </div>
  );
}

function StageRow({ stage }: { stage: StageProgress }) {
  const view = present(stage);
  const Icon = view.icon;
  const hasParts = stage.batched && stage.total_units !== null && stage.total_units !== undefined;
  const hasTokens =
    stage.estimated_input_tokens !== null && stage.estimated_input_tokens !== undefined
      ? stage.estimated_input_tokens > 0
      : false;
  const inFlight = stage.status === "processing" || stage.status === "failed";
  const analysed = (stage.successful_items ?? 0) + (stage.zero_result_items ?? 0);
  const review = stage.requires_review_items ?? 0;
  return (
    <li className={cn("rounded-md border px-3 py-2.5 text-sm", view.row)} data-stage={stage.stage} data-status={stage.status}>
      <div className="flex items-center justify-between gap-3">
        <div className={cn("flex min-w-0 items-center gap-2 font-medium", view.text)}>
          <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />
          <span className="truncate text-ink-950">{stage.label}</span>
        </div>
        <div className={cn("shrink-0 text-right text-xs font-semibold", view.text)}>
          {hasParts ? (
            <span aria-label={`${stage.completed_units} of ${stage.total_units} parts completed`}>
              {stage.completed_units} / {stage.total_units}
            </span>
          ) : (
            view.label
          )}
        </div>
      </div>

      {hasParts ? (
        <div className="mt-1.5 space-y-1 pl-6 text-xs text-ink-700">
          <p>
            <span className={view.text}>{view.label}</span>
            {stage.current_unit && inFlight ? ` · Part ${stage.current_unit} of ${stage.total_units}` : ""}
            {` · ${stage.provider_calls ?? 0} provider ${stage.provider_calls === 1 ? "call" : "calls"}`}
            {` · ${stage.retries ?? 0} ${stage.retries === 1 ? "retry" : "retries"}`}
          </p>
          {analysed > 0 || review > 0 ? (
            <p>
              {fmt(analysed)} analysed
              {review > 0 ? <span className="text-amber-200"> · {fmt(review)} need review</span> : null}
            </p>
          ) : null}
          {hasTokens ? (
            <p title="Actual values are reported by the provider; a dash means it reported none.">
              Tokens · estimated input {fmt(stage.estimated_input_tokens)} · actual input{" "}
              {fmt(stage.actual_input_tokens)} · output {fmt(stage.actual_output_tokens)} · total{" "}
              {fmt(stage.actual_total_tokens)}
            </p>
          ) : null}
          {stage.status === "failed" ? (
            <p className="text-amber-200">{providerPauseMessage(stage.last_provider_error_type)}</p>
          ) : null}
          {stage.parts && stage.parts.length > 0 ? <PartsStrip stage={stage.label} parts={stage.parts} /> : null}
        </div>
      ) : null}
    </li>
  );
}

/**
 * Real, persisted stage progress ("Financial Claims 2 / 6"). Every number comes
 * from the backend's durable batch ledger - nothing is estimated from elapsed
 * time, and no provider quota is implied.
 */
export function AnalysisStageProgress({ progress }: { progress: AnalysisProgress }) {
  const stages = progress.stages ?? [];
  const budget = stages.find((stage) => stage.configured_input_budget);
  const percent = Math.max(0, Math.min(100, progress.progress_percent));
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2 text-sm">
        <span className="font-medium text-ink-950">Overall progress</span>
        <span className="font-semibold text-ink-950">{percent}%</span>
      </div>
      <div
        className="h-2 rounded-full bg-white/10"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label="Overall progress"
      >
        <div className="h-2 rounded-full bg-ledger-500 shadow-glow transition-all" style={{ width: `${percent}%` }} />
      </div>
      {stages.length === 0 ? (
        <p className="mt-4 text-sm text-ink-700">Stage progress is not available for this run yet.</p>
      ) : (
        <ol className="mt-4 space-y-2" aria-label="Analysis stages">
          {stages.map((stage) => (
            <StageRow key={stage.stage} stage={stage} />
          ))}
        </ol>
      )}
      {budget ? (
        <p className="mt-3 text-xs text-ink-700">
          Requests are planned to about {fmt(budget.effective_input_budget)} input tokens each (
          {fmt(budget.configured_input_budget)} configured, minus a safety margin). This is a planning limit, not
          your provider quota.
        </p>
      ) : null}
    </div>
  );
}

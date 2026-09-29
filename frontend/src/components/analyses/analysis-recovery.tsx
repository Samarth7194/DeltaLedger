import { AlertTriangle, CheckCircle2, Loader2, PauseCircle, PlayCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import type { AnalysisProgress, AnalysisRun, AnalysisStageProgress } from "@/lib/api/types";

/** The stage the run failed in (the one the "paused" message is about), if any. */
export function failedStage(progress: AnalysisProgress): AnalysisStageProgress | undefined {
  return progress.stages?.find((stage) => stage.status === "failed");
}

/**
 * A failed run can be resumed only when the backend says running it again can
 * help. Everything else (running, completed, cancelled, waiting on a human
 * review, or a failure re-running cannot fix) has no Resume action.
 */
export function canResume(run: Pick<AnalysisRun, "status" | "progress">) {
  return run.status === "failed" && run.progress.retryable === true;
}

/**
 * A run whose status is still "in progress" but whose worker heartbeat has
 * gone stale - its worker almost certainly died before it could mark the run
 * failed. Distinct from `canResume` (which is the `status === "failed"`
 * case); both use the same POST /retry action underneath.
 */
export function isStalled(run: Pick<AnalysisRun, "status" | "progress">) {
  return run.status !== "failed" && run.progress.stale === true;
}

/** Calm, non-technical explanation of a provider-caused pause. No tracebacks. */
export function providerPauseMessage(errorType?: string | null): string {
  const saved = "Completed parts were saved and will not be repeated.";
  switch (errorType) {
    case "rate_limited_short_term":
    case "rate_limited":
      return `Processing paused due to a provider rate limit. ${saved}`;
    case "quota_exhausted_daily":
      return `Processing paused because the provider's daily quota was reached. ${saved} Resume after the quota resets.`;
    case "resource_exhausted":
      return `Processing paused because the provider reported it is out of capacity. ${saved}`;
    case "timeout":
    case "network_error":
    case "server_error":
      return `Processing paused due to a temporary provider connection problem. ${saved}`;
    default:
      return `Processing paused. ${saved}`;
  }
}

export function RecoveryNotice({
  run,
  resuming,
  resumeRequested,
  resumeError,
  onResume
}: {
  run: AnalysisRun;
  resuming: boolean;
  resumeRequested: boolean;
  resumeError?: string | null;
  onResume: () => void;
}) {
  if (isStalled(run)) {
    return (
      <Panel className="border-amber-300/30 bg-amber-400/10" role="status">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex gap-3 text-amber-100">
            <PauseCircle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <h3 className="font-semibold">Analysis stalled — recoverable</h3>
              <p className="mt-1 text-sm text-amber-100/85">
                This analysis stopped mid-step, most likely because the worker processing it was
                interrupted. Completed parts were saved and will not be repeated.
              </p>
              {resumeRequested ? (
                <p className="mt-2 flex items-center gap-2 text-sm text-emerald-200">
                  <CheckCircle2 aria-hidden="true" className="h-4 w-4" />
                  Retry requested. The worker will continue from the first incomplete part.
                </p>
              ) : null}
              {resumeError ? (
                <p className="mt-2 text-sm text-red-200" role="alert">
                  {resumeError}
                </p>
              ) : null}
            </div>
          </div>
          <Button
            type="button"
            variant="primary"
            className="no-print shrink-0"
            disabled={resuming || resumeRequested}
            onClick={onResume}
          >
            {resuming ? (
              <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
            ) : (
              <PlayCircle aria-hidden="true" className="h-4 w-4" />
            )}
            {resuming ? "Retrying…" : resumeRequested ? "Retry requested" : "Retry Analysis"}
          </Button>
        </div>
      </Panel>
    );
  }

  if (run.status !== "failed") {
    return null;
  }
  const stage = failedStage(run.progress);
  const resumable = canResume(run);

  if (!resumable) {
    return (
      <Panel className="border-red-300/25 bg-red-500/10" role="alert">
        <div className="flex gap-3 text-red-100">
          <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <h3 className="font-semibold">Analysis failed</h3>
            <p className="mt-1 text-sm text-red-100/80">
              This failure can&apos;t be fixed by running the analysis again.
              {run.failure_message ? ` ${run.failure_message}` : ""}
            </p>
          </div>
        </div>
      </Panel>
    );
  }

  return (
    <Panel className="border-amber-300/30 bg-amber-400/10" role="status">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex gap-3 text-amber-100">
          <PauseCircle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <h3 className="font-semibold">Analysis paused</h3>
            <p className="mt-1 text-sm text-amber-100/85">
              {providerPauseMessage(stage?.last_provider_error_type ?? run.failure_code)}
            </p>
            {stage?.retry_after_seconds ? (
              <p className="mt-1 text-xs text-amber-100/70">
                The provider suggested waiting about {Math.ceil(stage.retry_after_seconds)} seconds.
              </p>
            ) : null}
            {resumeRequested ? (
              <p className="mt-2 flex items-center gap-2 text-sm text-emerald-200">
                <CheckCircle2 aria-hidden="true" className="h-4 w-4" />
                Resume requested. The worker will continue from the first incomplete part.
              </p>
            ) : null}
            {resumeError ? (
              <p className="mt-2 text-sm text-red-200" role="alert">
                {resumeError}
              </p>
            ) : null}
          </div>
        </div>
        <Button
          type="button"
          variant="primary"
          className="no-print shrink-0"
          disabled={resuming || resumeRequested}
          onClick={onResume}
        >
          {resuming ? (
            <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
          ) : (
            <PlayCircle aria-hidden="true" className="h-4 w-4" />
          )}
          {resuming ? "Resuming…" : resumeRequested ? "Resume requested" : "Resume Analysis"}
        </Button>
      </div>
    </Panel>
  );
}

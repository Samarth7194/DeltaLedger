import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  RecoveryNotice,
  canResume,
  isStalled,
  providerPauseMessage
} from "@/components/analyses/analysis-recovery";
import { AnalysisStageProgress } from "@/components/analyses/analysis-stage-progress";
import { api } from "@/lib/api/endpoints";
import type { AnalysisProgress, AnalysisRun, AnalysisStageProgress as Stage } from "@/lib/api/types";
import { statusTone } from "@/lib/status";

function stage(overrides: Partial<Stage> & Pick<Stage, "stage" | "label">): Stage {
  return {
    status: "pending",
    batched: false,
    retryable: null,
    completed_units: null,
    total_units: null,
    current_unit: null,
    unit_label: null,
    provider_calls: null,
    retries: null,
    estimated_input_tokens: null,
    actual_input_tokens: null,
    actual_output_tokens: null,
    actual_total_tokens: null,
    configured_input_budget: null,
    effective_input_budget: null,
    successful_items: null,
    zero_result_items: null,
    requires_review_items: null,
    last_provider_error_type: null,
    retry_after_seconds: null,
    last_provider_error_at: null,
    parts: [],
    ...overrides
  };
}

const batched = {
  batched: true,
  unit_label: "parts",
  configured_input_budget: 12000,
  effective_input_budget: 9000
} as const;

function progress(overrides: Partial<AnalysisProgress> = {}): AnalysisProgress {
  return {
    status: "extracting_claims",
    current_node: "extract_financial_claims",
    completed_nodes: ["run_disclosure_comparison"],
    progress_percent: 42,
    stages: [
      stage({
        stage: "disclosure_comparison",
        label: "Disclosure Classification",
        status: "completed",
        ...batched,
        completed_units: 17,
        total_units: 17,
        provider_calls: 19,
        retries: 1,
        estimated_input_tokens: 130000,
        actual_input_tokens: 118250,
        actual_output_tokens: 31400,
        actual_total_tokens: 149650,
        successful_items: 131
      }),
      stage({
        stage: "financial_claims",
        label: "Financial Claims",
        status: "processing",
        ...batched,
        completed_units: 2,
        total_units: 6,
        current_unit: 3,
        provider_calls: 2,
        retries: 0,
        estimated_input_tokens: 40000,
        parts: [
          { index: 1, status: "completed" },
          { index: 2, status: "completed" },
          { index: 3, status: "processing" },
          { index: 4, status: "pending" }
        ] as Stage["parts"]
      }),
      stage({ stage: "xbrl_verification", label: "XBRL Verification" }),
      stage({ stage: "contradiction_analysis", label: "Contradiction Analysis" }),
      stage({ stage: "human_review", label: "Human Review" }),
      stage({ stage: "final_report", label: "Final Report" })
    ],
    ...overrides
  };
}

function run(overrides: Partial<AnalysisRun> = {}): AnalysisRun {
  return {
    id: "run-1234-5678",
    company_id: "c",
    current_filing_id: "f1",
    comparison_filing_id: "f2",
    comparison_id: "cmp",
    status: "failed",
    current_node: null,
    workflow_version: "v1",
    graph_version: "g1",
    requires_human_review: false,
    review_gate_reason: null,
    review_request_id: null,
    report_id: null,
    progress: progress({
      status: "failed",
      retryable: true,
      stages: progress().stages?.map((s) =>
        s.stage === "financial_claims"
          ? { ...s, status: "failed", retryable: true, last_provider_error_type: "rate_limited_short_term" }
          : s
      )
    }),
    counts: {},
    warnings: [],
    failure_code: "rate_limited",
    failure_message: "Provider request failed with a rate limit.",
    failure_node: "extract_financial_claims",
    ...overrides
  };
}

describe("analysis stage progress", () => {
  it("shows real part counts, calls, retries and token usage per stage", () => {
    render(<AnalysisStageProgress progress={progress()} />);

    const disclosure = screen.getByText("Disclosure Classification").closest("li") as HTMLElement;
    expect(within(disclosure).getByText("17 / 17")).toBeInTheDocument();
    expect(within(disclosure).getByText(/19 provider calls/)).toBeInTheDocument();
    expect(within(disclosure).getByText(/1 retry\b/)).toBeInTheDocument();
    expect(within(disclosure).getByText(/estimated input 130,000/)).toBeInTheDocument();
    expect(within(disclosure).getByText(/actual input 118,250/)).toBeInTheDocument();
    expect(within(disclosure).getByText(/output 31,400/)).toBeInTheDocument();
    expect(within(disclosure).getByText(/total 149,650/)).toBeInTheDocument();

    const claims = screen.getByText("Financial Claims").closest("li") as HTMLElement;
    expect(within(claims).getByText("2 / 6")).toBeInTheDocument();
    expect(within(claims).getByText(/Part 3 of 6/)).toBeInTheDocument();
    // Unreported provider usage is a dash, never an estimate presented as actual.
    expect(within(claims).getByText(/actual input —/)).toBeInTheDocument();
    expect(within(claims).getByRole("img", { name: /Financial Claims parts/ }).children).toHaveLength(4);
  });

  it("shows the not-yet-started stages as pending without invented numbers", () => {
    render(<AnalysisStageProgress progress={progress()} />);

    for (const label of ["XBRL Verification", "Contradiction Analysis", "Human Review", "Final Report"]) {
      const row = screen.getByText(label).closest("li") as HTMLElement;
      expect(row).toHaveAttribute("data-status", "pending");
      expect(within(row).getByText("Pending")).toBeInTheDocument();
      expect(within(row).queryByText(/\//)).not.toBeInTheDocument();
    }
  });

  it("renders overall progress from the backend value and never implies a provider quota", () => {
    const { container } = render(<AnalysisStageProgress progress={progress()} />);

    expect(screen.getByRole("progressbar", { name: "Overall progress" })).toHaveAttribute("aria-valuenow", "42");
    expect(screen.getByText(/planning limit, not your provider quota/)).toBeInTheDocument();
    expect(screen.getByText(/about 9,000 input tokens/)).toBeInTheDocument();
    expect(container.textContent?.toLowerCase()).not.toContain("remaining");
  });

  it("clamps out-of-range progress", () => {
    render(<AnalysisStageProgress progress={progress({ progress_percent: 140 })} />);

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });

  it("distinguishes requires-review, paused (retryable) and failed (non-retryable) stages", () => {
    const stages = [
      stage({
        stage: "disclosure_comparison",
        label: "Disclosure Classification",
        status: "requires_review",
        ...batched,
        completed_units: 17,
        total_units: 17,
        provider_calls: 17,
        retries: 0,
        successful_items: 128,
        requires_review_items: 3
      }),
      stage({
        stage: "financial_claims",
        label: "Financial Claims",
        status: "failed",
        retryable: true,
        ...batched,
        completed_units: 2,
        total_units: 6,
        current_unit: 3,
        provider_calls: 3,
        retries: 1,
        last_provider_error_type: "rate_limited_short_term"
      }),
      stage({ stage: "xbrl_verification", label: "XBRL Verification", status: "failed", retryable: false })
    ];
    render(<AnalysisStageProgress progress={progress({ stages })} />);

    const review = screen.getByText("Disclosure Classification").closest("li") as HTMLElement;
    expect(review).toHaveAttribute("data-status", "requires_review");
    expect(within(review).getByText(/3 need review/)).toBeInTheDocument();
    expect(within(review).getByText(/128 analysed/)).toBeInTheDocument();

    const paused = screen.getByText("Financial Claims").closest("li") as HTMLElement;
    expect(within(paused).getAllByText(/Paused – can resume/).length).toBeGreaterThan(0);
    expect(within(paused).getByText(/Processing paused due to a provider rate limit\./)).toBeInTheDocument();
    expect(within(paused).getByText(/Completed parts were saved and will not be repeated\./)).toBeInTheDocument();

    const failed = screen.getByText("XBRL Verification").closest("li") as HTMLElement;
    expect(within(failed).getByText("Failed")).toBeInTheDocument();
  });

  it("degrades gracefully for a run without stage data", () => {
    render(<AnalysisStageProgress progress={progress({ stages: undefined })} />);

    expect(screen.getByText(/Stage progress is not available/)).toBeInTheDocument();
  });

  it("uses warning styling for requires-review and completed-with-warnings statuses", () => {
    expect(statusTone("requires_review")).toBe("warning");
    expect(statusTone("completed_with_warnings")).toBe("warning");
    expect(statusTone("failed")).toBe("danger");
  });
});

describe("resume analysis UX", () => {
  it("offers Resume only for a failed run whose failure is retryable", () => {
    expect(canResume(run())).toBe(true);
    expect(canResume(run({ progress: { ...run().progress, retryable: false } }))).toBe(false);
    for (const status of ["completed", "cancelled", "processing_filings", "extracting_claims", "awaiting_human_review"]) {
      expect(canResume(run({ status }))).toBe(false);
    }
  });

  it("explains a rate-limit pause and resumes the same run on click", async () => {
    const onResume = vi.fn();
    render(<RecoveryNotice run={run()} resuming={false} resumeRequested={false} onResume={onResume} />);

    expect(screen.getByText("Analysis paused")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Processing paused due to a provider rate limit. Completed parts were saved and will not be repeated."
      )
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /resume analysis/i }));
    expect(onResume).toHaveBeenCalledTimes(1);
  });

  it("shows loading and confirmation states and prevents double submission", () => {
    const { rerender } = render(
      <RecoveryNotice run={run()} resuming resumeRequested={false} onResume={vi.fn()} />
    );
    expect(screen.getByRole("button", { name: /resuming/i })).toBeDisabled();

    rerender(<RecoveryNotice run={run()} resuming={false} resumeRequested onResume={vi.fn()} />);
    expect(screen.getByRole("button", { name: /resume requested/i })).toBeDisabled();
    expect(screen.getByText(/continue from the first incomplete part/)).toBeInTheDocument();
  });

  it("shows a backend error without hiding the button", () => {
    render(
      <RecoveryNotice
        run={run()}
        resuming={false}
        resumeRequested={false}
        resumeError="Only a failed analysis can be resumed."
        onResume={vi.fn()}
      />
    );

    expect(screen.getByText("Only a failed analysis can be resumed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /resume analysis/i })).toBeEnabled();
  });

  it("has no Resume action for a non-retryable failure and shows only the public message", () => {
    const failed = run({
      failure_code: "analysis_incomplete",
      failure_message: "Analysis is incomplete and cannot advance: financial claims: 1 of 6 batch(es) are not completed",
      progress: { ...run().progress, retryable: false }
    });
    render(<RecoveryNotice run={failed} resuming={false} resumeRequested={false} onResume={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /resume/i })).not.toBeInTheDocument();
    expect(screen.getByText(/can't be fixed by running the analysis again/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("renders nothing while running, when completed, or when waiting on a human review", () => {
    for (const status of ["extracting_claims", "completed", "awaiting_human_review", "cancelled"]) {
      const { container, unmount } = render(
        <RecoveryNotice run={run({ status })} resuming={false} resumeRequested={false} onResume={vi.fn()} />
      );
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });

  it("maps provider error types to calm messages and never leaks internals", () => {
    expect(providerPauseMessage("quota_exhausted_daily")).toMatch(/daily quota was reached/);
    expect(providerPauseMessage("quota_exhausted_daily")).toMatch(/after the quota resets/);
    expect(providerPauseMessage("timeout")).toMatch(/temporary provider connection problem/);
    expect(providerPauseMessage("resource_exhausted")).toMatch(/out of capacity/);
    expect(providerPauseMessage(null)).toMatch(/^Processing paused\./);
    for (const type of ["rate_limited_short_term", "timeout", null, "unexpected_thing"]) {
      expect(providerPauseMessage(type)).not.toMatch(/traceback|exception|stack|Error:/i);
    }
  });
});

function staleRun(overrides: Partial<AnalysisRun> = {}): AnalysisRun {
  return run({
    status: "verifying_claims",
    current_node: "verify_financial_claims",
    failure_code: null,
    failure_message: null,
    failure_node: null,
    progress: progress({ status: "verifying_claims", retryable: true, stale: true }),
    ...overrides
  });
}

describe("stalled run recovery UX", () => {
  it("treats a stale in-progress run as recoverable, distinct from a failed one", () => {
    expect(isStalled(staleRun())).toBe(true);
    expect(isStalled(run())).toBe(false); // failed, not stale
    expect(
      isStalled(run({ status: "verifying_claims", progress: { ...run().progress, stale: false } }))
    ).toBe(false);
  });

  it("shows a distinct 'stalled — recoverable' notice with a Retry button", () => {
    render(<RecoveryNotice run={staleRun()} resuming={false} resumeRequested={false} onResume={vi.fn()} />);

    expect(screen.getByText("Analysis stalled — recoverable")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry analysis/i })).toBeInTheDocument();
    // Not the failed-run copy.
    expect(screen.queryByText("Analysis paused")).not.toBeInTheDocument();
    expect(screen.queryByText("Analysis failed")).not.toBeInTheDocument();
  });

  it("calls the same onResume handler on click, and shows loading/requested states", async () => {
    const onResume = vi.fn();
    const { rerender } = render(
      <RecoveryNotice run={staleRun()} resuming={false} resumeRequested={false} onResume={onResume} />
    );

    await userEvent.click(screen.getByRole("button", { name: /retry analysis/i }));
    expect(onResume).toHaveBeenCalledTimes(1);

    rerender(<RecoveryNotice run={staleRun()} resuming resumeRequested={false} onResume={onResume} />);
    expect(screen.getByRole("button", { name: /retrying/i })).toBeDisabled();

    rerender(<RecoveryNotice run={staleRun()} resuming={false} resumeRequested onResume={onResume} />);
    expect(screen.getByRole("button", { name: /retry requested/i })).toBeDisabled();
    expect(screen.getByText(/continue from the first incomplete part/)).toBeInTheDocument();
  });

  it("shows a backend error (e.g. lock still held) without hiding the button", () => {
    render(
      <RecoveryNotice
        run={staleRun()}
        resuming={false}
        resumeRequested={false}
        resumeError="A worker is currently processing this analysis; it is not stalled."
        onResume={vi.fn()}
      />
    );

    expect(
      screen.getByText("A worker is currently processing this analysis; it is not stalled.")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry analysis/i })).toBeEnabled();
  });
});

describe("resume request", () => {
  afterEach(() => vi.restoreAllMocks());

  it("posts to the retry endpoint of the SAME run and never creates a new analysis", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ data: { analysis_run_id: "run-1", job_id: "j", status: "failed" }, meta: {}, error: null }),
        { status: 202, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.retryAnalysis("run-1");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/analyses\/run-1\/retry$/);
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });
});

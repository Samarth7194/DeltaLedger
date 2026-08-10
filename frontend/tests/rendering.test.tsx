import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { DisclosureSideBySide } from "@/components/disclosures/disclosure-change-list";
import { EvidenceList } from "@/components/evidence/evidence-viewer";
import { FinancialVerificationDetail } from "@/components/financial/financial-verification-panel";
import { InconsistencyDetail } from "@/components/contradictions/inconsistency-list";
import { ReportView } from "@/components/reports/report-view";
import { ReviewPanel } from "@/components/review/review-panel";
import { formatDate, formatPercentagePoint, formatPercent } from "@/lib/formatters";
import { activeAnalysisRefetchMs, labelFor } from "@/lib/status";

import {
  claim,
  disclosureChange,
  evidence,
  factCandidate,
  finding,
  report,
  reviewRequest,
  verification
} from "./fixtures";

describe("status and financial formatting", () => {
  it("maps backend values to analyst labels and polling cadence", () => {
    expect(labelFor("approximately_verified")).toBe("Approximately Verified");
    expect(labelFor("awaiting_human_review")).toBe("Awaiting Human Review");
    expect(activeAnalysisRefetchMs("running")).toBe(5000);
    expect(activeAnalysisRefetchMs("completed")).toBe(false);
  });

  it("distinguishes percent and percentage points", () => {
    expect(formatPercent(11.83)).toBe("11.83%");
    expect(formatPercentagePoint(0.17)).toBe("+0.17 percentage points");
    expect(formatDate(null)).toBe("Not available");
    expect(formatDate("not-a-date")).toBe("Not available");
  });
});

describe("analyst evidence surfaces", () => {
  it("renders side-by-side disclosure comparison evidence", () => {
    render(<DisclosureSideBySide change={disclosureChange} />);

    expect(screen.getByText("Weakened")).toBeInTheDocument();
    expect(screen.getAllByText(/access to external financing/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/subject to market conditions/).length).toBeGreaterThan(0);
    expect(screen.getByText("Liquidity")).toBeInTheDocument();
  });

  it("renders financial verification detail and XBRL candidates", () => {
    renderWithQuery(
      <FinancialVerificationDetail
        claim={claim}
        verification={verification}
        factCandidates={[factCandidate]}
      />
    );

    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("12.00%")).toBeInTheDocument();
    expect(screen.getByText("11.83%")).toBeInTheDocument();
    expect(screen.getByText("+0.17 percentage points")).toBeInTheDocument();
    expect(screen.getByText("fact-current")).toBeInTheDocument();
  });

  it("renders potential inconsistency without allegation language", () => {
    render(<InconsistencyDetail finding={finding} onOpenEvidence={vi.fn()} />);

    expect(screen.getByText("Potential Inconsistency.")).toBeInTheDocument();
    expect(screen.getByText("Increase")).toBeInTheDocument();
    expect(screen.getByText("Decrease")).toBeInTheDocument();
    expect(screen.queryByText(/fraud|lie|deception/i)).not.toBeInTheDocument();
  });

  it("renders evidence rows", () => {
    render(<EvidenceList evidence={[evidence]} />);

    expect(screen.getByText("Revenue increased 12%.")).toBeInTheDocument();
    expect(screen.getByText("Item 2")).toBeInTheDocument();
  });
});

describe("review, resume, and report", () => {
  it("submits review once and enables resume after non-pending review", async () => {
    const submit = vi.fn();
    const resume = vi.fn();
    render(
      <ReviewPanel
        review={{ ...reviewRequest, status: "approved" }}
        onSubmit={submit}
        onResume={resume}
      />
    );

    expect(screen.getByRole("button", { name: /submit review/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /resume analysis/i }));
    expect(resume).toHaveBeenCalledTimes(1);
  });

  it("renders structured report sections and limitations", () => {
    render(<ReportView report={report} />);

    expect(screen.getByText("Executive Summary")).toBeInTheDocument();
    expect(screen.getAllByText("Potential Inconsistencies").length).toBeGreaterThan(0);
    expect(screen.getByText("Ambiguous XBRL fact")).toBeInTheDocument();
    expect(screen.getByText("Review Outcomes")).toBeInTheDocument();
  });
});

function renderWithQuery(ui: ReactElement) {
  const queryClient = new QueryClient();
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

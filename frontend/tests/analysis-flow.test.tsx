import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { NewAnalysisForm } from "@/components/analyses/new-analysis-form";

import { company, filings } from "./fixtures";

describe("new analysis flow", () => {
  it("keeps the company selector usable when filings fail to load", async () => {
    const user = userEvent.setup();
    const onCompanyChange = vi.fn();
    const otherCompany = {
      ...company,
      id: "company-2",
      ticker: "MSFT",
      legal_name: "Microsoft Corporation"
    };
    render(
      <NewAnalysisForm
        companies={[company, otherCompany]}
        filings={[]}
        filingsError={new Error("Filing lookup failed")}
        selectedCompanyId={company.id}
        onCompanyChange={onCompanyChange}
        onSubmit={vi.fn()}
      />
    );

    const selector = screen.getByLabelText(/company/i);
    await user.selectOptions(selector, otherCompany.id);

    expect(onCompanyChange).toHaveBeenCalledWith(otherCompany.id);
    expect(selector).toBeEnabled();
    expect(screen.getByText("Filing lookup failed")).toBeInTheDocument();
  });

  it("prevents invalid current and previous filing selection", async () => {
    const submit = vi.fn();
    render(
      <NewAnalysisForm
        companies={[company]}
        filings={filings}
        selectedCompanyId={company.id}
        onCompanyChange={vi.fn()}
        onSubmit={submit}
      />
    );

    await userEvent.click(screen.getAllByRole("button", { name: /current/i })[1]);
    await userEvent.click(screen.getAllByRole("button", { name: /previous/i })[0]);

    expect(screen.getByRole("button", { name: /create analysis/i })).toBeDisabled();
    expect(submit).not.toHaveBeenCalled();
  });

  it("submits a valid older comparison and later current filing pair", async () => {
    const submit = vi.fn();
    render(
      <NewAnalysisForm
        companies={[company]}
        filings={filings}
        selectedCompanyId={company.id}
        onCompanyChange={vi.fn()}
        onSubmit={submit}
      />
    );

    await userEvent.click(screen.getAllByRole("button", { name: /current/i })[0]);
    await userEvent.click(screen.getAllByRole("button", { name: /previous/i })[1]);
    await userEvent.click(screen.getByRole("button", { name: /create analysis/i }));

    expect(submit).toHaveBeenCalledWith("filing-current", "filing-previous");
  });
});

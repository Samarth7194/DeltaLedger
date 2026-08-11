import { expect, type Page, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

import { ids, mockDeltaLedgerApi } from "./fixtures";

type PageWithErrors = Page & { __deltaLedgerErrors?: string[] };

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  (page as PageWithErrors).__deltaLedgerErrors = errors;
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/") && response.status() >= 400) {
      errors.push(`${response.status()} ${response.url()}`);
    }
  });
  await mockDeltaLedgerApi(page);
});

test.afterEach(async ({ page }) => {
  expect((page as PageWithErrors).__deltaLedgerErrors ?? []).toEqual([]);
});

test("critical browser analysis flow reaches review, resumes, and renders report", async ({
  page
}, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Recent Analyses/i })).toBeVisible();

  await page.getByRole("link", { name: /Companies/i }).click();
  await expect(page.getByRole("heading", { name: "Companies" })).toBeVisible();
  await Promise.all([
    page.waitForURL(`/companies/${ids.companyId}`),
    page.getByRole("link", { name: "AAPL", exact: true }).click()
  ]);
  await expect(page.getByRole("heading", { name: "AAPL" })).toBeVisible();
  await expect(page.getByText("Jun 29, 2024").first()).toBeVisible();

  await page.getByRole("link", { name: /New Analysis/i }).click();
  await page.getByRole("button", { name: "Current" }).first().click();
  await page.getByRole("button", { name: "Previous" }).last().click();
  await page.getByRole("button", { name: /Create Analysis/i }).click();

  await expect(page).toHaveURL(new RegExp(`/analyses/${ids.analysisId}`));
  await expect(page.getByText("Comparing Disclosures").first()).toBeVisible();
  await page.getByRole("button", { name: /Refresh/i }).click();
  await expect(page.getByText("Verifying Claims").first()).toBeVisible();
  await page.getByRole("button", { name: /Refresh/i }).click();
  await expect(page.getByText("Awaiting Human Review").first()).toBeVisible();

  await page.getByRole("button", { name: /Potential Inconsistencies/i }).click();
  await expect(page.getByText("Potential Inconsistency.")).toBeVisible();
  await expect(
    page.getByText("Numerical Claim Differs From Official Data").first()
  ).toBeVisible();
  await expect(page.getByText(/Company lied|Fraud detected|Deceptive company/i)).toHaveCount(0);
  await page.getByRole("button", { name: /Open Evidence/i }).click();
  await expect(page.getByRole("dialog", { name: /Finding Evidence/i })).toBeVisible();
  await expect(page.getByText("Part I Item 2")).toBeVisible();
  await expect(page.getByText("RevenueFromContractWithCustomerExcludingAssessedTax")).toBeVisible();
  await page.getByRole("button", { name: "Close", exact: true }).click();

  await page.getByRole("button", { name: "Review" }).click();
  await page.getByLabel("Review decision").selectOption("approved");
  await page.getByLabel("Analyst note").fill("Evidence reviewed.");
  await page.getByRole("button", { name: /Submit Review/i }).click();
  await expect(page.getByRole("button", { name: /Resume Analysis/i })).toBeEnabled();
  await page.getByRole("button", { name: /Resume Analysis/i }).click();
  await expect(page.getByText("Generating Report").first()).toBeVisible();
  await page.getByRole("button", { name: /Refresh/i }).click();
  await expect(page.getByText("Completed").first()).toBeVisible();

  await page.getByRole("button", { name: "Report" }).click();
  await expect(page.getByRole("heading", { name: "Executive Summary" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Disclosure Changes" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Financial Verification Summary" })
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Potential Inconsistencies" })
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "High-Priority Findings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Review Outcomes" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Limitations" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Evidence Manifest" })).toBeVisible();

  const [file] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "JSON" }).click()
  ]);
  expect(file.suggestedFilename()).toContain(ids.analysisId);
  const downloadPath = testInfo.outputPath(file.suggestedFilename());
  await file.saveAs(downloadPath);
  const payload = JSON.parse(await readFile(downloadPath, "utf-8"));
  expect(payload.analysis_run_id).toBe(ids.analysisId);
  expect(JSON.stringify(payload)).not.toContain("checkpoint_thread_id");
});

test("invalid filing pair prevents analysis submission", async ({ page }) => {
  await page.goto(`/analyses/new?companyId=${ids.companyId}`);
  await page.getByRole("button", { name: "Current" }).last().click();
  await page.getByRole("button", { name: "Previous" }).first().click();
  await expect(page.getByRole("button", { name: /Create Analysis/i })).toBeDisabled();
  await expect(page.getByText(/Select a current filing with a later report period/i)).toBeVisible();
});

test("workflow progress labels follow backend status transitions", async ({ page }) => {
  await page.goto(`/analyses/${ids.analysisId}`);
  await expect(page.getByText("Comparing Disclosures").first()).toBeVisible();
  await page.getByRole("button", { name: /Refresh/i }).click();
  await expect(page.getByText("Verifying Claims").first()).toBeVisible();
  await page.getByRole("button", { name: /Refresh/i }).click();
  await expect(page.getByText("Awaiting Human Review").first()).toBeVisible();
});

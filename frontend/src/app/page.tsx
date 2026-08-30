"use client";

import { AlertTriangle, BrainCircuit, Database, FileSearch, FolderSearch, GitCompareArrows, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Metric } from "@/components/ui/metric";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { PageHeader, SignalPill } from "@/components/ui/product";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/state";
import { formatDate } from "@/lib/formatters";
import { useAnalyses, useCompanies } from "@/lib/queries/hooks";
import { labelFor } from "@/lib/status";

export default function DashboardPage() {
  const analyses = useAnalyses({ limit: 8 });
  const companies = useCompanies({ limit: 6 });

  if (analyses.isLoading || companies.isLoading) {
    return <SkeletonRows rows={6} />;
  }
  if (analyses.error || companies.error) {
    return <ErrorState error={analyses.error ?? companies.error} />;
  }

  const runs = analyses.data ?? [];
  const visibleCompanies = companies.data ?? [];
  const awaiting = runs.filter((run) => run.status === "awaiting_human_review");
  const completed = runs.filter((run) => run.status === "completed" || run.status === "completed_with_warnings");
  const failed = runs.filter((run) => run.status === "failed" || run.status === "cancelled");
  const filingCount = visibleCompanies.reduce((total, company) => total + company.filing_count, 0);
  const inconsistencyCount = runs.reduce((total, run) => total + numericCount(run.counts.contradictions), 0);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="DeltaLedger AI"
        title="Financial Disclosure Intelligence"
        description="Compare SEC filings across periods, retrieve source evidence, verify claims against official XBRL facts, and route unresolved findings to analyst review."
        action={
          <Link href="/analyses/new">
            <Button type="button" variant="primary">
              <FolderSearch aria-hidden="true" className="h-4 w-4" />
              New Analysis
            </Button>
          </Link>
        }
      >
        <div className="flex flex-wrap gap-2">
          <SignalPill tone="success">Gemini structured analysis</SignalPill>
          <SignalPill tone="success">Gemini embeddings</SignalPill>
          <SignalPill>Hybrid retrieval</SignalPill>
          <SignalPill>XBRL verification</SignalPill>
          <SignalPill tone="warning">Human review</SignalPill>
        </div>
      </PageHeader>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric label="Companies Loaded" value={visibleCompanies.length} detail="Current dashboard query" icon={<Database className="h-4 w-4" />} />
        <Metric label="SEC Filings Indexed" value={filingCount} detail="Across loaded companies" icon={<FileSearch className="h-4 w-4" />} />
        <Metric label="Recent Analyses" value={runs.length} detail="Latest workflow runs" icon={<GitCompareArrows className="h-4 w-4" />} />
        <Metric
          label="Requires Review"
          value={awaiting.length}
          detail={`${inconsistencyCount} potential inconsistencies`}
          tone={awaiting.length ? "warning" : "success"}
          icon={<ShieldCheck className="h-4 w-4" />}
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel>
          <PanelHeader title="Recent Analyses" eyebrow="Workflow intelligence" detail="Recent filing comparisons, review gates, warnings, and run status." />
          {runs.length ? (
            <div className="grid gap-3">
              {runs.map((run) => (
                <Link
                  key={run.id}
                  href={`/analyses/${run.id}`}
                  className="group rounded-md border border-white/10 bg-white/[0.04] p-4 outline-none transition hover:border-ledger-200/30 hover:bg-white/[0.07] focus-visible:ring-2 focus-visible:ring-ledger-500"
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm font-semibold text-ledger-200">{run.id.slice(0, 8)}</span>
                        <Badge value={run.status} />
                        {run.requires_human_review ? <Badge value="awaiting_human_review" /> : null}
                      </div>
                      <p className="mt-2 text-sm text-ink-700">
                        Current filing {run.current_filing_id.slice(0, 8)} compared with previous filing {run.comparison_filing_id.slice(0, 8)}
                      </p>
                    </div>
                    <div className="min-w-32 text-left sm:text-right">
                      <div className="text-sm font-semibold text-ink-950">{run.progress.progress_percent}%</div>
                      <div className="mt-1 h-1.5 rounded-full bg-white/10">
                        <div className="h-1.5 rounded-full bg-ledger-500" style={{ width: `${clampPercent(run.progress.progress_percent)}%` }} />
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 grid gap-2 text-xs text-ink-700 sm:grid-cols-3">
                    <span>{labelFor(run.current_node)}</span>
                    <span>{run.warnings.length} warnings</span>
                    <span>{run.requires_human_review ? "Analyst gate active" : "No review gate"}</span>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState title="No analyses yet" detail="Create an analysis from two processed SEC filings to populate this workspace." />
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Coverage" eyebrow="Monitored companies" />
          {visibleCompanies.length ? (
            <div className="space-y-3">
              {visibleCompanies.map((company) => (
                <Link
                  key={company.id}
                  href={`/companies/${company.id}`}
                  className="block rounded-md border border-white/10 bg-white/[0.04] p-3 outline-none transition hover:border-ledger-200/30 hover:bg-white/[0.07] focus-visible:ring-2 focus-visible:ring-ledger-500"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-semibold text-ink-950">{company.ticker ?? company.cik}</div>
                    <Badge value={company.latest_ingestion_status} />
                  </div>
                  <p className="mt-1 text-sm text-ink-700">{company.legal_name}</p>
                  <p className="mt-2 text-xs text-ink-700">
                    {company.filing_count} filings indexed - Latest period {formatDate(company.latest_report_period)}
                  </p>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState title="No companies indexed" detail="SEC company data has not yet been ingested for this environment." />
          )}
        </Panel>
      </div>

      {failed.length ? (
        <Panel className="border-red-300/25 bg-red-500/10">
          <div className="flex items-start gap-3 text-red-100">
            <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5" />
            <div>
              <h2 className="font-semibold">Failures or cancellations require attention</h2>
              <p className="mt-1 text-sm text-red-100/80">
                {failed.length} recent workflow run returned a failed or cancelled state.
              </p>
            </div>
          </div>
        </Panel>
      ) : null}

      <Panel>
        <PanelHeader title="AI System" eyebrow="Capability map" />
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {[
            ["Gemini structured analysis", "Disclosure classification and extraction"],
            ["Gemini embeddings", "1024-dimensional retrieval vectors"],
            ["Hybrid retrieval", "Dense and lexical evidence search"],
            ["XBRL verification", "Official facts and calculations"],
            ["Human review", "Responsible analyst approval gates"]
          ].map(([title, detail]) => (
            <div key={title} className="rounded-md border border-white/10 bg-white/[0.04] p-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-ink-950">
                <BrainCircuit aria-hidden="true" className="h-4 w-4 text-ledger-200" />
                {title}
              </div>
              <p className="mt-2 text-xs leading-5 text-ink-700">{detail}</p>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function numericCount(value: unknown) {
  return typeof value === "number" ? value : 0;
}

function clampPercent(value: number) {
  return Math.max(0, Math.min(100, value));
}

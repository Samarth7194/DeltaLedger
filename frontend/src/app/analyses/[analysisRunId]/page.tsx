"use client";

import { AlertTriangle, Ban, Clock3, RefreshCcw } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { RecoveryNotice } from "@/components/analyses/analysis-recovery";
import { AnalysisStageProgress } from "@/components/analyses/analysis-stage-progress";
import { WorkflowEvents } from "@/components/analyses/workflow-events";
import { WorkflowProgress } from "@/components/analyses/workflow-progress";
import { InconsistencyList } from "@/components/contradictions/inconsistency-list";
import { DisclosureChangeList } from "@/components/disclosures/disclosure-change-list";
import { EvidenceViewer } from "@/components/evidence/evidence-viewer";
import { FinancialVerificationPanel } from "@/components/financial/financial-verification-panel";
import { ReportView } from "@/components/reports/report-view";
import { ReviewPanel } from "@/components/review/review-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Metric } from "@/components/ui/metric";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { PageHeader, SignalPill } from "@/components/ui/product";
import { SkeletonRows, ErrorState } from "@/components/ui/state";
import { Tabs } from "@/components/ui/tabs";
import {
  useAnalysis,
  useAnalysisEvents,
  useCancelAnalysis,
  useContradictionEvidence,
  useContradictions,
  useDisclosureChanges,
  useFinancialClaims,
  useFinancialVerifications,
  useReport,
  useResumeAnalysis,
  useRetryAnalysis,
  useReviewRequest,
  useWorkflowReview
} from "@/lib/queries/hooks";
import { labelFor } from "@/lib/status";

const tabs = [
  { id: "overview", label: "Overview" },
  { id: "changes", label: "Disclosure Changes" },
  { id: "verification", label: "Financial Verification" },
  { id: "inconsistencies", label: "Potential Inconsistencies" },
  { id: "evidence", label: "Evidence" },
  { id: "review", label: "Review" },
  { id: "report", label: "Report" }
];

export default function AnalysisWorkspacePage() {
  const params = useParams<{ analysisRunId: string }>();
  const analysisRunId = stringParam(params.analysisRunId);
  const [activeTab, setActiveTab] = useState("overview");
  const [evidenceFindingId, setEvidenceFindingId] = useState<string | null>(null);
  const analysis = useAnalysis(analysisRunId);
  const events = useAnalysisEvents(analysisRunId, Boolean(analysis.data));
  const review = useReviewRequest(analysisRunId, analysis.data?.status === "awaiting_human_review");
  const workflowReview = useWorkflowReview(analysisRunId);
  const resume = useResumeAnalysis(analysisRunId);
  const retry = useRetryAnalysis(analysisRunId);
  const [resumeRequested, setResumeRequested] = useState(false);
  const cancel = useCancelAnalysis(analysisRunId);
  const report = useReport(analysisRunId, Boolean(analysis.data?.report_id || activeTab === "report"));
  const comparisonId = analysis.data?.comparison_id;
  const changes = useDisclosureChanges(comparisonId, { limit: 100 });
  const claims = useFinancialClaims(comparisonId, { limit: 100 });
  const verifications = useFinancialVerifications(comparisonId);
  const contradictions = useContradictions(comparisonId, { limit: 100 });
  const evidence = useContradictionEvidence(evidenceFindingId);

  const runStatus = analysis.data?.status;
  const runStale = analysis.data?.progress.stale === true;
  const refetchAnalysis = analysis.refetch;
  useEffect(() => {
    // After "Resume"/"Retry" a failed run stays `failed`, and a stalled run
    // keeps its old in-progress status and `stale: true`, until the worker
    // picks it back up; poll briefly so the page follows it, and stop once
    // neither condition holds any more (it started running again, or reached
    // a terminal status).
    if (!resumeRequested) {
      return;
    }
    if (runStatus !== "failed" && !runStale) {
      setResumeRequested(false);
      return;
    }
    const timer = setInterval(() => void refetchAnalysis(), 3_000);
    return () => clearInterval(timer);
  }, [resumeRequested, runStatus, runStale, refetchAnalysis]);

  if (analysis.isLoading) {
    return <SkeletonRows rows={8} />;
  }
  if (analysis.error || !analysis.data) {
    return <ErrorState error={analysis.error ?? new Error("Analysis run not found.")} />;
  }

  const run = analysis.data;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Analysis workspace"
        title={`Run ${run.id.slice(0, 8)}`}
        description="Follow a filing comparison from retrieval through verification, contradiction detection, evidence inspection, human review, and final reporting."
        action={
          <div className="flex flex-wrap gap-2 no-print">
            <Button type="button" onClick={() => analysis.refetch()}>
              <RefreshCcw aria-hidden="true" className="h-4 w-4" />
              Refresh
            </Button>
            <Button
              type="button"
              variant="danger"
              disabled={["completed", "failed", "cancelled"].includes(run.status) || cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              <Ban aria-hidden="true" className="h-4 w-4" />
              Cancel
            </Button>
          </div>
        }
      >
        <div className="flex flex-wrap gap-2">
          <Badge value={run.status} />
          <SignalPill>{labelFor(run.current_node)}</SignalPill>
          {run.requires_human_review ? <SignalPill tone="warning">Review required</SignalPill> : null}
          {run.failure_code ? <Badge value="failed" label={run.failure_code} /> : null}
        </div>
      </PageHeader>

      <RecoveryNotice
        run={run}
        resuming={retry.isPending}
        resumeRequested={resumeRequested}
        resumeError={retry.error instanceof Error ? retry.error.message : null}
        onResume={() =>
          retry.mutate(undefined, {
            onSuccess: () => setResumeRequested(true)
          })
        }
      />

      {run.progress.stages?.some((stage) => stage.status === "requires_review") ? (
        <Panel className="border-amber-300/30 bg-amber-400/10">
          <div className="flex gap-3 text-amber-100">
            <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <h3 className="font-semibold">Some passages need review</h3>
              <p className="mt-1 text-sm text-amber-100/85">
                The model could not analyse some passages. They are flagged for an analyst and the report carries a
                data-quality warning.
              </p>
            </div>
          </div>
        </Panel>
      ) : null}

      <Panel className="p-0">
        <Tabs tabs={tabs} active={activeTab} onChange={setActiveTab} />
      </Panel>

      {activeTab === "overview" ? (
        <div className="space-y-5">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Metric label="Disclosure Changes" value={count(run.counts.disclosure_changes)} />
            <Metric label="Financial Claims" value={count(run.counts.financial_claims)} />
            <Metric label="Verified Claims" value={count(run.counts.verified_claims)} />
            <Metric
              label="Potential Inconsistencies"
              value={count(run.counts.contradictions)}
              tone={count(run.counts.contradictions) ? "warning" : "neutral"}
            />
          </div>
          <Panel>
            <PanelHeader
              title="Analysis Progress"
              eyebrow={labelFor(run.current_node)}
              detail="Completed parts are saved as they finish, so an interrupted run continues from the first incomplete part."
            />
            <AnalysisStageProgress progress={run.progress} />
          </Panel>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
            <Panel>
              <PanelHeader title="Workflow Progress" eyebrow={labelFor(run.current_node)} />
              <WorkflowProgress progress={run.progress} />
            </Panel>
            <Panel>
              <PanelHeader title="Run Context" eyebrow="Filing pair" />
              <div className="grid gap-3 text-sm">
                <div className="rounded-md border border-white/10 bg-white/[0.04] p-3">
                  <div className="text-xs font-medium text-ink-700">Current filing</div>
                  <div className="mt-1 break-all font-mono text-ink-950">{run.current_filing_id}</div>
                </div>
                <div className="rounded-md border border-white/10 bg-white/[0.04] p-3">
                  <div className="text-xs font-medium text-ink-700">Comparison filing</div>
                  <div className="mt-1 break-all font-mono text-ink-950">{run.comparison_filing_id}</div>
                </div>
                <div className="flex items-center gap-2 text-ink-700">
                  <Clock3 aria-hidden="true" className="h-4 w-4 text-ledger-200" />
                  {run.warnings.length} workflow warnings captured
                </div>
              </div>
            </Panel>
          </div>
          <Panel>
            <PanelHeader title="Workflow Events" eyebrow="History" />
            {events.isLoading ? <SkeletonRows rows={4} /> : <WorkflowEvents events={events.data ?? []} />}
          </Panel>
        </div>
      ) : null}

      {activeTab === "changes" ? (
        <Panel>
          <PanelHeader title="Disclosure Changes" eyebrow="Narrative delta" />
          {changes.isLoading ? <SkeletonRows rows={5} /> : null}
          {changes.error ? <ErrorState error={changes.error} /> : null}
          {!changes.isLoading && !changes.error ? <DisclosureChangeList changes={changes.data ?? []} /> : null}
        </Panel>
      ) : null}

      {activeTab === "verification" ? (
        <Panel>
          <PanelHeader title="Financial Verification" eyebrow="Official XBRL check" />
          {claims.isLoading || verifications.isLoading ? <SkeletonRows rows={5} /> : null}
          {claims.error || verifications.error ? <ErrorState error={claims.error ?? verifications.error} /> : null}
          {!claims.isLoading && !verifications.isLoading && !claims.error && !verifications.error ? (
            <FinancialVerificationPanel claims={claims.data ?? []} verifications={verifications.data ?? []} />
          ) : null}
        </Panel>
      ) : null}

      {activeTab === "inconsistencies" ? (
        <Panel>
          <PanelHeader title="Potential Inconsistencies" eyebrow="Narrative versus numbers" />
          {contradictions.isLoading ? <SkeletonRows rows={5} /> : null}
          {contradictions.error ? <ErrorState error={contradictions.error} /> : null}
          {!contradictions.isLoading && !contradictions.error ? (
            <InconsistencyList
              findings={contradictions.data ?? []}
              onOpenEvidence={(findingId) => {
                setEvidenceFindingId(findingId);
                setActiveTab("evidence");
              }}
            />
          ) : null}
        </Panel>
      ) : null}

      {activeTab === "evidence" ? (
        <Panel>
          <PanelHeader title="Evidence" eyebrow="Source support" />
          {contradictions.isLoading ? <SkeletonRows rows={5} /> : null}
          {contradictions.error ? <ErrorState error={contradictions.error} /> : null}
          {!contradictions.isLoading && !contradictions.error ? (
            <InconsistencyList findings={contradictions.data ?? []} onOpenEvidence={setEvidenceFindingId} />
          ) : null}
        </Panel>
      ) : null}

      {activeTab === "review" ? (
        <ReviewPanel
          review={review.data}
          submitting={workflowReview.isPending}
          resuming={resume.isPending}
          onSubmit={(status, comment) => workflowReview.mutate({ status, comment })}
          onResume={() => resume.mutate()}
        />
      ) : null}

      {activeTab === "report" ? (
        report.isLoading ? (
          <SkeletonRows rows={5} />
        ) : report.error ? (
          <ErrorState error={report.error} />
        ) : (
          <ReportView report={report.data} />
        )
      ) : null}

      <EvidenceViewer
        open={Boolean(evidenceFindingId)}
        title="Finding Evidence"
        loading={evidence.isLoading}
        evidence={evidence.data}
        onClose={() => setEvidenceFindingId(null)}
      />
    </div>
  );
}

function count(value: unknown) {
  return typeof value === "number" ? value : 0;
}

function stringParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : (value ?? "");
}

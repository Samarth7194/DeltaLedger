"use client";

import { AlertTriangle, Ban, RefreshCcw } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

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
import { SkeletonRows, ErrorState } from "@/components/ui/state";
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
  useReviewRequest,
  useWorkflowReview
} from "@/lib/queries/hooks";
import { labelFor } from "@/lib/status";

const tabs = [
  "Overview",
  "Disclosure Changes",
  "Financial Verification",
  "Potential Inconsistencies",
  "Evidence",
  "Review",
  "Report"
];

export default function AnalysisWorkspacePage() {
  const params = useParams<{ analysisRunId: string }>();
  const analysisRunId = stringParam(params.analysisRunId);
  const [activeTab, setActiveTab] = useState("Overview");
  const [evidenceFindingId, setEvidenceFindingId] = useState<string | null>(null);
  const analysis = useAnalysis(analysisRunId);
  const events = useAnalysisEvents(analysisRunId, Boolean(analysis.data));
  const review = useReviewRequest(analysisRunId, analysis.data?.status === "awaiting_human_review");
  const workflowReview = useWorkflowReview(analysisRunId);
  const resume = useResumeAnalysis(analysisRunId);
  const cancel = useCancelAnalysis(analysisRunId);
  const report = useReport(analysisRunId, Boolean(analysis.data?.report_id || activeTab === "Report"));
  const comparisonId = analysis.data?.comparison_id;
  const changes = useDisclosureChanges(comparisonId, { limit: 100 });
  const claims = useFinancialClaims(comparisonId, { limit: 100 });
  const verifications = useFinancialVerifications(comparisonId);
  const contradictions = useContradictions(comparisonId, { limit: 100 });
  const evidence = useContradictionEvidence(evidenceFindingId);

  if (analysis.isLoading) {
    return <SkeletonRows rows={8} />;
  }
  if (analysis.error || !analysis.data) {
    return <ErrorState error={analysis.error ?? new Error("Analysis run not found.")} />;
  }

  const run = analysis.data;

  return (
    <div className="space-y-5">
      <Panel>
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
              Analysis Workspace
            </p>
            <h2 className="text-xl font-semibold">Run {run.id.slice(0, 8)}</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge value={run.status} />
              {run.requires_human_review ? <Badge value="awaiting_human_review" /> : null}
              {run.failure_code ? <Badge value="failed" label={run.failure_code} /> : null}
            </div>
          </div>
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
        </div>
      </Panel>

      {run.failure_message ? (
        <Panel className="border-red-200 bg-red-50">
          <div className="flex gap-3 text-red-900">
            <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5" />
            <div>
              <h3 className="font-semibold">Analysis failed</h3>
              <p className="mt-1 text-sm">{run.failure_message}</p>
            </div>
          </div>
        </Panel>
      ) : null}

      <div className="overflow-x-auto border-b border-stone-200 no-print">
        <div className="flex min-w-max gap-1">
          {tabs.map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`border-b-2 px-3 py-3 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ledger-600 ${
                activeTab === tab
                  ? "border-ledger-700 text-ledger-700"
                  : "border-transparent text-stone-600"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {activeTab === "Overview" ? (
        <div className="space-y-5">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Metric label="Disclosure Changes" value={count(run.counts.disclosure_changes)} />
            <Metric label="Financial Claims" value={count(run.counts.financial_claims)} />
            <Metric label="Verified Claims" value={count(run.counts.verified_claims)} />
            <Metric label="Potential Inconsistencies" value={count(run.counts.contradictions)} />
          </div>
          <Panel>
            <PanelHeader title="Workflow Progress" eyebrow={labelFor(run.current_node)} />
            <WorkflowProgress progress={run.progress} />
          </Panel>
          <Panel>
            <PanelHeader title="Workflow Events" eyebrow="History" />
            {events.isLoading ? <SkeletonRows rows={4} /> : <WorkflowEvents events={events.data ?? []} />}
          </Panel>
        </div>
      ) : null}

      {activeTab === "Disclosure Changes" ? (
        <Panel>
          <PanelHeader title="Disclosure Changes" eyebrow="What changed?" />
          {changes.isLoading ? <SkeletonRows rows={5} /> : null}
          {changes.error ? <ErrorState error={changes.error} /> : null}
          {!changes.isLoading && !changes.error ? <DisclosureChangeList changes={changes.data ?? []} /> : null}
        </Panel>
      ) : null}

      {activeTab === "Financial Verification" ? (
        <Panel>
          <PanelHeader title="Financial Verification" eyebrow="Do official numbers support the claim?" />
          {claims.isLoading || verifications.isLoading ? <SkeletonRows rows={5} /> : null}
          {claims.error || verifications.error ? <ErrorState error={claims.error ?? verifications.error} /> : null}
          {!claims.isLoading && !verifications.isLoading && !claims.error && !verifications.error ? (
            <FinancialVerificationPanel claims={claims.data ?? []} verifications={verifications.data ?? []} />
          ) : null}
        </Panel>
      ) : null}

      {activeTab === "Potential Inconsistencies" ? (
        <Panel>
          <PanelHeader title="Potential Inconsistencies" eyebrow="Is there a potential inconsistency?" />
          {contradictions.isLoading ? <SkeletonRows rows={5} /> : null}
          {contradictions.error ? <ErrorState error={contradictions.error} /> : null}
          {!contradictions.isLoading && !contradictions.error ? (
            <InconsistencyList
              findings={contradictions.data ?? []}
              onOpenEvidence={(findingId) => {
                setEvidenceFindingId(findingId);
                setActiveTab("Evidence");
              }}
            />
          ) : null}
        </Panel>
      ) : null}

      {activeTab === "Evidence" ? (
        <Panel>
          <PanelHeader title="Evidence" eyebrow="What evidence proves the finding?" />
          <InconsistencyList findings={contradictions.data ?? []} onOpenEvidence={setEvidenceFindingId} />
        </Panel>
      ) : null}

      {activeTab === "Review" ? (
        <ReviewPanel
          review={review.data}
          submitting={workflowReview.isPending}
          resuming={resume.isPending}
          onSubmit={(status, comment) => workflowReview.mutate({ status, comment })}
          onResume={() => resume.mutate()}
        />
      ) : null}

      {activeTab === "Report" ? (
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

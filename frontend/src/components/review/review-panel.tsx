"use client";

import { RotateCcw, Send } from "lucide-react";
import { useState } from "react";

import type { AnalysisReviewRequest } from "@/lib/api/types";
import { labelFor } from "@/lib/status";

import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Panel, PanelHeader } from "../ui/panel";
import { EmptyState } from "../ui/state";

const workflowStatuses = ["approved", "rejected", "partially_approved", "needs_changes", "uncertain"];

export function ReviewPanel({
  review,
  onSubmit,
  onResume,
  submitting,
  resuming
}: {
  review?: AnalysisReviewRequest;
  onSubmit: (status: string, comment: string) => void;
  onResume: () => void;
  submitting?: boolean;
  resuming?: boolean;
}) {
  const [status, setStatus] = useState("approved");
  const [comment, setComment] = useState("");

  if (!review) {
    return (
      <Panel>
        <EmptyState
          title="No workflow review request"
          detail="When an analysis reaches a human-review gate, the required review appears here."
        />
      </Panel>
    );
  }
  const canResume = review.status !== "pending";

  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PanelHeader title={labelFor(review.review_type)} eyebrow="Human review" />
        <Badge value={review.status} />
      </div>
      <p className="mt-3 text-sm leading-6 text-ink-700">{review.reason}</p>
      <dl className="mt-4 grid gap-3 sm:grid-cols-3">
        <ReviewMetric label="Findings" value={review.finding_ids.length} />
        <ReviewMetric label="Claims" value={review.claim_ids.length} />
        <ReviewMetric label="Verifications" value={review.verification_ids.length} />
      </dl>

      <div className="mt-5 grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
        <div>
          <label className="text-sm font-medium text-ink-950" htmlFor="review-status">
            Review decision
          </label>
          <select
            id="review-status"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            disabled={submitting || review.status !== "pending"}
            className="mt-2 w-full rounded-md border border-white/12 bg-graphite-950 px-3 py-2 text-sm text-ink-950 outline-none focus-visible:ring-2 focus-visible:ring-ledger-500 disabled:opacity-60"
          >
            {workflowStatuses.map((item) => (
              <option key={item} value={item}>
                {labelFor(item)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-sm font-medium text-ink-950" htmlFor="review-comment">
            Analyst note
          </label>
          <textarea
            id="review-comment"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            disabled={submitting || review.status !== "pending"}
            rows={4}
            className="mt-2 w-full rounded-md border border-white/12 bg-graphite-950 px-3 py-2 text-sm text-ink-950 outline-none focus-visible:ring-2 focus-visible:ring-ledger-500 disabled:opacity-60"
          />
        </div>
      </div>

      <div className="mt-5 flex flex-wrap gap-2 no-print">
        <Button
          type="button"
          variant="primary"
          disabled={submitting || review.status !== "pending"}
          onClick={() => onSubmit(status, comment)}
        >
          <Send aria-hidden="true" className="h-4 w-4" />
          Submit Review
        </Button>
        <Button type="button" disabled={!canResume || resuming} onClick={onResume}>
          <RotateCcw aria-hidden="true" className="h-4 w-4" />
          Resume Analysis
        </Button>
      </div>
    </Panel>
  );
}

function ReviewMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-white/10 bg-white/[0.04] p-3">
      <dt className="text-xs font-semibold uppercase text-ink-700">{label}</dt>
      <dd className="mt-1 text-lg font-semibold text-ink-950">{value}</dd>
    </div>
  );
}

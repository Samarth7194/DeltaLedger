"use client";

import { RotateCcw, Send } from "lucide-react";
import { useState } from "react";

import type { AnalysisReviewRequest } from "@/lib/api/types";
import { labelFor } from "@/lib/status";

import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { EmptyState } from "../ui/state";

const workflowStatuses = [
  "approved",
  "rejected",
  "partially_approved",
  "needs_changes",
  "uncertain"
];

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
      <EmptyState
        title="No workflow review request"
        detail="When an analysis reaches a human-review gate, the required review appears here."
      />
    );
  }
  const canResume = review.status !== "pending";

  return (
    <section className="rounded-md border border-stone-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
            Human Review
          </p>
          <h3 className="text-base font-semibold">{labelFor(review.review_type)}</h3>
        </div>
        <Badge value={review.status} />
      </div>
      <p className="mt-3 text-sm leading-6 text-stone-700">{review.reason}</p>
      <dl className="mt-4 grid gap-3 sm:grid-cols-3">
        <ReviewMetric label="Findings" value={review.finding_ids.length} />
        <ReviewMetric label="Claims" value={review.claim_ids.length} />
        <ReviewMetric label="Verifications" value={review.verification_ids.length} />
      </dl>

      <div className="mt-5 grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
        <div>
          <label className="text-sm font-medium" htmlFor="review-status">
            Review decision
          </label>
          <select
            id="review-status"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            disabled={submitting || review.status !== "pending"}
            className="mt-2 w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ledger-600 disabled:bg-stone-100"
          >
            {workflowStatuses.map((item) => (
              <option key={item} value={item}>
                {labelFor(item)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-sm font-medium" htmlFor="review-comment">
            Analyst note
          </label>
          <textarea
            id="review-comment"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            disabled={submitting || review.status !== "pending"}
            rows={4}
            className="mt-2 w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ledger-600 disabled:bg-stone-100"
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
    </section>
  );
}

function ReviewMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-stone-200 bg-stone-50 p-3">
      <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-stone-500">{label}</dt>
      <dd className="mt-1 text-lg font-semibold">{value}</dd>
    </div>
  );
}

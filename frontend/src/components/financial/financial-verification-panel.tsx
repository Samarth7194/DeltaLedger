"use client";

import { Calculator, Database } from "lucide-react";
import { useMemo, useState } from "react";

import type { ClaimFactCandidate, ClaimVerification, FinancialClaim } from "@/lib/api/types";
import {
  compactJson,
  formatConfidence,
  formatNumber,
  formatPercentagePoint,
  formatPercent
} from "@/lib/formatters";
import { useFactCandidates } from "@/lib/queries/hooks";
import { labelFor } from "@/lib/status";
import { cn } from "@/lib/utils";

import { Badge } from "../ui/badge";
import { EmptyState } from "../ui/state";

export function FinancialVerificationPanel({
  claims,
  verifications,
  factCandidates = []
}: {
  claims: FinancialClaim[];
  verifications: ClaimVerification[];
  factCandidates?: ClaimFactCandidate[];
}) {
  const [selectedClaimId, setSelectedClaimId] = useState(claims[0]?.id ?? "");
  const selectedClaim = useMemo(
    () => claims.find((claim) => claim.id === selectedClaimId) ?? claims[0],
    [claims, selectedClaimId]
  );
  const selectedVerification = verifications.find(
    (verification) => verification.financial_claim_id === selectedClaim?.id
  );
  const fetchedCandidates = useFactCandidates(selectedClaim?.id);
  const candidates = factCandidates ?? fetchedCandidates.data ?? [];

  if (claims.length === 0) {
    return (
      <EmptyState
        title="No financial claims found"
        detail="Claims extracted from filing language appear here after verification runs."
      />
    );
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
      <div className="space-y-2">
        {claims.map((claim) => {
          const verification = verifications.find((item) => item.financial_claim_id === claim.id);
          return (
            <button
              key={claim.id}
              type="button"
              onClick={() => setSelectedClaimId(claim.id)}
              className={cn(
                "w-full rounded-md border p-3 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-ledger-500",
                selectedClaim?.id === claim.id
                  ? "border-ledger-200/40 bg-ledger-500/10"
                  : "border-white/10 bg-white/[0.04] hover:border-ledger-200/30 hover:bg-white/[0.07]"
              )}
            >
              <div className="flex flex-wrap gap-2">
                <Badge value={verification?.verification_status ?? claim.review_status} />
                <Badge value={claim.claim_type} />
              </div>
              <h3 className="mt-2 text-sm font-semibold text-ink-950">
                {claim.canonical_metric_name ?? "Unresolved metric"}
              </h3>
              <p className="mt-1 line-clamp-3 text-xs text-ink-700">{claim.claim_text}</p>
            </button>
          );
        })}
      </div>
      {selectedClaim ? (
        <FinancialVerificationDetail
          claim={selectedClaim}
          verification={selectedVerification}
          factCandidates={candidates.filter((candidate) => candidate.financial_claim_id === selectedClaim.id)}
        />
      ) : null}
    </div>
  );
}

export function FinancialVerificationDetail({
  claim,
  verification,
  factCandidates
}: {
  claim: FinancialClaim;
  verification?: ClaimVerification;
  factCandidates: ClaimFactCandidate[];
}) {
  return (
    <article className="rounded-md border border-white/10 bg-white/[0.04] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge value={verification?.verification_status ?? claim.review_status} />
        <span className="text-sm text-ink-700">{formatConfidence(claim.extraction_confidence)}</span>
      </div>
      <h3 className="mt-3 text-base font-semibold text-ink-950">
        {claim.canonical_metric_name ?? "Financial claim"}
      </h3>
      <blockquote className="mt-3 rounded-md border border-white/10 bg-graphite-950/60 p-3 text-sm leading-6 text-ink-800">
        {claim.claim_text}
      </blockquote>

      <dl className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTerm label="Reported" value={formatClaimValue(claim.reported_change ?? claim.reported_value)} />
        <MetricTerm label="Calculated" value={formatClaimValue(verification?.percentage_change)} />
        <MetricTerm
          label="Difference"
          value={formatPercentagePoint(verification?.reported_vs_calculated_difference)}
        />
        <MetricTerm label="Tolerance" value={formatNumber(verification?.tolerance_used)} />
      </dl>

      {verification ? (
        <section className="mt-4 rounded-md border border-white/10 bg-graphite-950/60 p-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink-950">
            <Calculator aria-hidden="true" className="h-4 w-4 text-ledger-200" />
            Verification Calculation
          </div>
          <p className="mt-2 text-sm leading-6 text-ink-700">{verification.verification_reason}</p>
          <pre className="mt-3 max-h-44 overflow-auto rounded-md bg-graphite-950 p-3 text-xs text-ink-900">
            {compactJson({
              formula: verification.formula,
              inputs: verification.calculation_inputs,
              output: verification.calculation_output
            })}
          </pre>
        </section>
      ) : (
        <EmptyState title="No verification yet" detail="Verification details appear after the backend resolves XBRL facts." />
      )}

      <section className="mt-4 rounded-md border border-white/10 bg-graphite-950/60 p-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink-950">
          <Database aria-hidden="true" className="h-4 w-4 text-ledger-200" />
          XBRL Fact Candidates
        </div>
        {factCandidates.length ? (
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full divide-y divide-white/10 text-left text-xs">
              <thead className="text-ink-700">
                <tr>
                  <th className="px-2 py-2">Role</th>
                  <th className="px-2 py-2">Score</th>
                  <th className="px-2 py-2">Selection</th>
                  <th className="px-2 py-2">Fact ID</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10 text-ink-900">
                {factCandidates.map((candidate) => (
                  <tr key={candidate.id}>
                    <td className="px-2 py-2">{labelFor(candidate.candidate_role)}</td>
                    <td className="px-2 py-2">{formatNumber(candidate.combined_score)}</td>
                    <td className="px-2 py-2">{labelFor(candidate.selection_status)}</td>
                    <td className="px-2 py-2 font-mono">{candidate.xbrl_fact_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-2 text-sm text-ink-700">No fact candidates returned for this claim.</p>
        )}
      </section>
    </article>
  );
}

function MetricTerm({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/10 bg-graphite-950/60 p-3">
      <dt className="text-xs font-semibold uppercase text-ink-700">{label}</dt>
      <dd className="mt-1 text-sm font-semibold text-ink-950">{value}</dd>
    </div>
  );
}

function formatClaimValue(value?: number | string | null) {
  return formatPercent(value);
}

"""The single place that decides whether an analysis may advance to human
review and the final report.

An analysis must never advance just because *some* batches completed. This
evaluates every upstream stage against explicit conditions, using the durable
batch ledger plus the workflow's own record of what ran:

* Disclosure classification: comparison completed, and every planned batch
  completed (the count planned is recorded by the comparison itself).
* Financial claims: the extraction node ran, and every planned batch
  completed.
* XBRL verification, contradiction analysis, evidence validation: their nodes
  ran and reported completion.
* Human review (report stage only): if the workflow required review, a
  non-pending review outcome exists.

Items the model could not analyse (`requires_review`) do not block the report -
they are surfaced as data-quality warnings that the report must carry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.db.models.workflow import (
    BATCH_STAGE_DISCLOSURE_COMPARISON,
    BATCH_STAGE_FINANCIAL_CLAIMS,
)
from app.repositories.stage_batch_repository import StageProgress


@dataclass(frozen=True)
class ReadinessProblem:
    stage: str
    code: str
    message: str


@dataclass
class ReadinessReport:
    blockers: list[ReadinessProblem] = field(default_factory=list)
    # Non-blocking: work that finished but is incomplete in a way the report
    # must state (e.g. passages that need an analyst).
    data_quality: list[str] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return not self.blockers

    def summary(self) -> str:
        return "; ".join(f"{p.stage}: {p.message}" for p in self.blockers)


def evaluate_readiness(
    *,
    completed_nodes: Sequence[str],
    batches: Mapping[str, StageProgress],
    comparison_status: str | None,
    comparison_metrics: Mapping[str, object] | None,
    claim_metrics: Mapping[str, object] | None,
    verification_complete: bool,
    contradiction_complete: bool,
    evidence_valid: bool,
    for_report: bool = False,
    requires_human_review: bool = False,
    review_status: str | None = None,
) -> ReadinessReport:
    report = ReadinessReport()

    def block(stage: str, code: str, message: str) -> None:
        report.blockers.append(ReadinessProblem(stage, code, message))

    # -- disclosure classification ---------------------------------------
    if "run_disclosure_comparison" not in completed_nodes or comparison_status != "completed":
        block(
            "disclosure_classification",
            "comparison_incomplete",
            "the disclosure comparison has not completed",
        )
    else:
        _check_batched_stage(
            report,
            "disclosure_classification",
            batches.get(BATCH_STAGE_DISCLOSURE_COMPARISON),
            planned=_int_or_none((comparison_metrics or {}).get("classification_batches_total")),
            # A comparison completed by an earlier run is reused as-is and this
            # run recorded no batches for it; its `completed` status (set only
            # after every batch finished) is the proof in that case.
            require_records=False,
            block=block,
        )

    # -- financial claims ------------------------------------------------
    if "extract_financial_claims" not in completed_nodes:
        block("financial_claims", "extraction_incomplete", "claim extraction has not completed")
    else:
        _check_batched_stage(
            report,
            "financial_claims",
            batches.get(BATCH_STAGE_FINANCIAL_CLAIMS),
            planned=_int_or_none((claim_metrics or {}).get("claim_batches_total")),
            # Claim extraction runs (and records its batches) in every run.
            require_records=True,
            block=block,
        )

    # -- deterministic stages --------------------------------------------
    if "verify_financial_claims" not in completed_nodes or not verification_complete:
        block("xbrl_verification", "verification_incomplete", "XBRL verification has not finished")
    if "analyze_contradictions" not in completed_nodes or not contradiction_complete:
        block(
            "contradiction_analysis",
            "contradictions_incomplete",
            "contradiction analysis has not finished",
        )
    if "validate_evidence" not in completed_nodes or not evidence_valid:
        block("evidence_validation", "evidence_unvalidated", "evidence has not been validated")

    # -- human review ------------------------------------------------------
    if for_report and requires_human_review and review_status in (None, "pending"):
        block("human_review", "review_pending", "required human review has not been completed")
    return report


def _check_batched_stage(
    report: ReadinessReport,
    stage: str,
    progress: StageProgress | None,
    *,
    planned: int | None,
    require_records: bool,
    block,
) -> None:
    label = stage.replace("_", " ")
    if progress is None:
        if planned and require_records:
            block(stage, "batches_missing", f"{planned} planned {label} batch(es) have no record")
        # planned == 0: every item was resolved without the model; nothing to
        # batch. planned unknown: nothing recorded either - nothing to verify.
        return
    if planned is not None and progress.total != planned:
        block(
            stage,
            "batch_count_mismatch",
            f"{label} planned {planned} batch(es) but {progress.total} are recorded",
        )
    unfinished = progress.total - progress.completed
    if unfinished:
        block(
            stage,
            "batches_unfinished",
            f"{unfinished} of {progress.total} {label} batch(es) are not completed",
        )
    if progress.requires_review_items:
        report.data_quality.append(
            f"{progress.requires_review_items} passage(s) could not be analysed by the model "
            f"during {label} and need analyst review."
        )


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None

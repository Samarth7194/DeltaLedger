from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.openai_compatible import ProviderRequestError
from app.core.config import Settings
from app.db.models import (
    AnalysisReviewRequest,
    AnalysisRun,
    ContradictionFinding,
    Filing,
    FilingChunk,
    FilingSection,
)
from app.repositories.comparison_repository import ComparisonRepository
from app.repositories.contradiction_repository import ContradictionRepository
from app.repositories.filing_repository import FilingRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.services.analysis_report_service import AnalysisReportService
from app.services.contradiction_analysis_service import ContradictionAnalysisService
from app.services.filing_comparison_service import FilingComparisonError, FilingComparisonService
from app.services.filing_processing_service import FilingProcessingService
from app.services.financial_verification_service import FinancialVerificationService

WORKFLOW_NODES = [
    "validate_analysis_request",
    "ensure_filings_available",
    "ensure_filings_processed",
    "run_disclosure_comparison",
    "extract_financial_claims",
    "verify_financial_claims",
    "analyze_contradictions",
    "validate_evidence",
    "prioritize_findings",
    "review_gate",
    "generate_report",
    "finalize_analysis",
]
SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_MEMORY_CHECKPOINTER = None
_POSTGRES_CHECKPOINTERS = {}


class AnalysisState(TypedDict, total=False):
    analysis_run_id: str
    company_id: str
    current_filing_id: str
    comparison_filing_id: str
    comparison_id: str | None
    disclosure_change_ids: list[str]
    financial_claim_ids: list[str]
    claim_verification_ids: list[str]
    contradiction_finding_ids: list[str]
    review_request_id: str | None
    report_id: str | None
    filings_ready: bool
    processing_ready: bool
    comparison_complete: bool
    financial_verification_complete: bool
    contradiction_analysis_complete: bool
    evidence_valid: bool
    requires_human_review: bool
    review_result: dict[str, object] | None
    warnings: list[str]
    recoverable_errors: list[dict[str, object]]
    fatal_errors: list[dict[str, object]]
    workflow_status: str
    completed_nodes: list[str]
    counts: dict[str, object]


class WorkflowError(Exception):
    def __init__(
        self,
        category: str,
        code: str,
        public_message: str,
        *,
        node: str | None = None,
    ) -> None:
        super().__init__(public_message)
        self.category = category
        self.code = code
        self.public_message = public_message
        self.node = node


class AnalysisWorkflowService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.workflow = WorkflowRepository(session)
        self.filings = FilingRepository(session)
        self.comparisons = ComparisonRepository(session)
        self.financial = FinancialRepository(session)
        self.contradictions = ContradictionRepository(session)

    async def create_analysis(
        self,
        *,
        current_filing_id: uuid.UUID,
        comparison_filing_id: uuid.UUID,
    ) -> tuple[AnalysisRun, bool]:
        current = await self.filings.get(current_filing_id)
        previous = await self.filings.get(comparison_filing_id)
        if current is None or previous is None:
            raise WorkflowError("validation_error", "filing_not_found", "Both filings must exist.")
        if current.company_id != previous.company_id:
            raise WorkflowError(
                "validation_error",
                "different_companies",
                "Filings must belong to the same company.",
            )
        run, created = await self.workflow.create_or_get_run(
            current_filing=current,
            comparison_filing=previous,
            workflow_version=self.settings.analysis_workflow_version,
            graph_version=self.settings.analysis_graph_version,
        )
        if created:
            await self.workflow.add_event(
                analysis_run_id=run.id,
                event_type="workflow_started",
                event_payload={"status": "queued"},
            )
        await self.session.commit()
        return run, created

    async def run_analysis(self, analysis_run_id: uuid.UUID) -> AnalysisRun:
        run = await self._require_run(analysis_run_id)
        state: AnalysisState = {
            "analysis_run_id": str(run.id),
            "company_id": str(run.company_id),
            "current_filing_id": str(run.current_filing_id),
            "comparison_filing_id": str(run.comparison_filing_id),
            "comparison_id": str(run.comparison_id) if run.comparison_id else None,
            "warnings": [],
            "recoverable_errors": [],
            "fatal_errors": [],
            "workflow_status": run.status,
            "completed_nodes": _completed_nodes(run.processing_metrics),
            "counts": {},
        }
        await self._invoke_graph(run, state)
        refreshed = await self._require_run(analysis_run_id)
        await self.session.commit()
        return refreshed

    async def resume_analysis(
        self,
        analysis_run_id: uuid.UUID,
        review_request_id: uuid.UUID,
    ) -> AnalysisRun:
        run = await self._require_run(analysis_run_id)
        review = await self.workflow.get_latest_review(analysis_run_id)
        if review is None or review.id != review_request_id:
            raise WorkflowError(
                "validation_error",
                "review_not_found",
                "Review request was not found for this analysis.",
            )
        if review.status == "pending":
            raise WorkflowError(
                "validation_error",
                "review_pending",
                "Review must be submitted before resume.",
            )
        if run.status != "awaiting_human_review":
            raise WorkflowError(
                "validation_error",
                "resume_not_allowed",
                "Analysis can only resume from awaiting human review.",
            )
        await self.workflow.add_event(
            analysis_run_id=analysis_run_id,
            event_type="workflow_resumed",
            event_payload={"review_request_id": str(review.id), "review_status": review.status},
        )
        graph = await self._compile_graph()
        await graph.ainvoke(
            Command(
                resume={
                    "review_request_id": str(review.id),
                    "status": review.status,
                    "review_payload": review.review_payload or {},
                }
            ),
            config={"configurable": {"thread_id": run.checkpoint_thread_id}},
        )
        refreshed = await self._require_run(analysis_run_id)
        await self.session.commit()
        return refreshed

    async def cancel_analysis(self, analysis_run_id: uuid.UUID) -> AnalysisRun:
        run = await self._require_run(analysis_run_id)
        if run.status in {"completed", "completed_with_warnings", "failed", "cancelled"}:
            return run
        await self.workflow.set_run_status(run, "cancelled", current_node=None)
        await self.workflow.add_event(
            analysis_run_id=run.id,
            event_type="workflow_cancelled",
            event_payload={"safe_cancellation": True},
        )
        await self.session.commit()
        return run

    async def submit_review(
        self,
        analysis_run_id: uuid.UUID,
        *,
        status: str,
        reviewed_by: str | None,
        comment: str | None,
        payload: dict[str, object] | None,
    ) -> AnalysisReviewRequest:
        review = await self.workflow.get_pending_review(analysis_run_id)
        if review is None:
            raise WorkflowError(
                "validation_error",
                "review_not_pending",
                "No pending workflow review exists for this analysis.",
            )
        updated = await self.workflow.submit_review(
            review,
            status=status,
            reviewed_by=reviewed_by,
            comment=comment,
            payload=payload,
        )
        await self.workflow.add_event(
            analysis_run_id=analysis_run_id,
            event_type="review_completed",
            event_payload={"review_request_id": str(updated.id), "status": updated.status},
        )
        await self.session.commit()
        return updated

    async def _compile_graph(self):
        graph = StateGraph(AnalysisState)
        graph.add_node("validate_analysis_request", self._validate_analysis_request)
        graph.add_node("ensure_filings_available", self._ensure_filings_available)
        graph.add_node("ensure_filings_processed", self._ensure_filings_processed)
        graph.add_node("run_disclosure_comparison", self._run_disclosure_comparison)
        graph.add_node("extract_financial_claims", self._extract_financial_claims)
        graph.add_node("verify_financial_claims", self._verify_financial_claims)
        graph.add_node("analyze_contradictions", self._analyze_contradictions)
        graph.add_node("validate_evidence", self._validate_evidence)
        graph.add_node("prioritize_findings", self._prioritize_findings)
        graph.add_node("review_gate", self._review_gate)
        graph.add_node("generate_report", self._generate_report)
        graph.add_node("finalize_analysis", self._finalize_analysis)
        graph.add_edge(START, "validate_analysis_request")
        graph.add_edge("validate_analysis_request", "ensure_filings_available")
        graph.add_edge("ensure_filings_available", "ensure_filings_processed")
        graph.add_edge("ensure_filings_processed", "run_disclosure_comparison")
        graph.add_edge("run_disclosure_comparison", "extract_financial_claims")
        graph.add_edge("extract_financial_claims", "verify_financial_claims")
        graph.add_edge("verify_financial_claims", "analyze_contradictions")
        graph.add_edge("analyze_contradictions", "validate_evidence")
        graph.add_edge("validate_evidence", "prioritize_findings")
        graph.add_edge("prioritize_findings", "review_gate")
        graph.add_conditional_edges(
            "review_gate",
            _review_route,
            {"generate_report": "generate_report", "end": END},
        )
        graph.add_edge("generate_report", "finalize_analysis")
        graph.add_edge("finalize_analysis", END)
        return graph.compile(checkpointer=await create_workflow_checkpointer(self.settings))

    async def _invoke_graph(self, run: AnalysisRun, state: AnalysisState) -> None:
        # Snapshot the primary key before invoking the graph: a node's own
        # service (e.g. FilingComparisonService) may roll back this shared
        # session on failure, which expires every object in the identity
        # map, `run` included. Reading `run.id`/`run.current_node`
        # synchronously afterwards would then trigger an implicit lazy
        # refresh outside the async greenlet context (MissingGreenlet),
        # masking the real error. `run_id` is captured now, while `run` is
        # still fresh, and any post-failure state is re-fetched explicitly.
        run_id = run.id
        graph = await self._compile_graph()
        try:
            result = await graph.ainvoke(
                state,
                config={"configurable": {"thread_id": run.checkpoint_thread_id}},
            )
            if isinstance(result, dict) and result.get("__interrupt__"):
                return
        except WorkflowError as exc:
            await self._fail_run(run_id, exc)
            raise
        except ProviderRequestError as exc:
            workflow_error = WorkflowError(
                "provider_error",
                exc.error_category,
                _provider_error_message(exc),
                node=await self._current_node_for_error(run_id),
            )
            await self._fail_run(run_id, workflow_error)
            raise
        except Exception as exc:
            workflow_error = WorkflowError(
                "fatal_internal_error",
                exc.__class__.__name__,
                "Analysis workflow failed unexpectedly.",
                node=await self._current_node_for_error(run_id),
            )
            await self._fail_run(run_id, workflow_error)
            raise

    async def _current_node_for_error(self, analysis_run_id: uuid.UUID) -> str | None:
        """Re-fetch current_node instead of trusting an in-memory attribute.

        This performs its own await-bounded query, so it safely refreshes an
        expired object instead of triggering an implicit lazy load from
        plain synchronous attribute access.
        """
        run = await self.workflow.get_run(analysis_run_id)
        return run.current_node if run is not None else None

    async def _validate_analysis_request(self, state: AnalysisState) -> AnalysisState:
        async def work() -> AnalysisState:
            current, previous = await self._filing_pair(state)
            if current.company_id != previous.company_id:
                raise WorkflowError(
                    "validation_error",
                    "different_companies",
                    "Filings must belong to the same company.",
                )
            if current.id == previous.id:
                raise WorkflowError(
                    "validation_error",
                    "same_filing",
                    "Current and comparison filings must differ.",
                )
            if current.form_type != "10-Q" or previous.form_type != "10-Q":
                raise WorkflowError(
                    "validation_error",
                    "unsupported_form",
                    "Phase 6 MVP supports 10-Q comparisons.",
                )
            current_period = current.report_period or current.filing_date
            previous_period = previous.report_period or previous.filing_date
            if current_period <= previous_period:
                raise WorkflowError(
                    "validation_error",
                    "invalid_period_order",
                    "Current filing must be newer than comparison filing.",
                )
            return {"company_id": str(current.company_id), "workflow_status": "validating"}

        return await self._node("validate_analysis_request", state, "validating", work)

    async def _ensure_filings_available(self, state: AnalysisState) -> AnalysisState:
        async def work() -> AnalysisState:
            current, previous = await self._filing_pair(state)
            warnings = list(state.get("warnings", []))
            for filing in (current, previous):
                if filing.ingestion_status == "failed":
                    raise WorkflowError(
                        "missing_dependency",
                        "filing_ingestion_failed",
                        "One required filing is marked failed.",
                    )
                if not filing.storage_key:
                    warnings.append(f"Filing {filing.id} has no stored source document.")
            return {"filings_ready": True, "warnings": warnings}

        return await self._node("ensure_filings_available", state, "preparing_filings", work)

    async def _ensure_filings_processed(self, state: AnalysisState) -> AnalysisState:
        async def work() -> AnalysisState:
            current, previous = await self._filing_pair(state)
            warnings = list(state.get("warnings", []))
            processor = FilingProcessingService(self.session, self.settings)
            for filing in (current, previous):
                if await self._has_processing_ready(filing.id):
                    continue
                if filing.storage_key:
                    await processor.process_filing(filing.id)
                else:
                    warnings.append(f"Filing {filing.id} cannot be processed without storage_key.")
            current_ready = await self._has_processing_ready(current.id)
            previous_ready = await self._has_processing_ready(previous.id)
            ready = current_ready and previous_ready
            if not ready:
                raise WorkflowError(
                    "missing_dependency",
                    "filings_not_processed",
                    "Required filings do not have parsed sections and chunks.",
                )
            return {"processing_ready": True, "warnings": warnings}

        return await self._node("ensure_filings_processed", state, "processing_filings", work)

    async def _run_disclosure_comparison(self, state: AnalysisState) -> AnalysisState:
        async def work() -> AnalysisState:
            service = FilingComparisonService(self.session, self.settings)
            try:
                result = await service.create_comparison(
                    current_filing_id=uuid.UUID(state["current_filing_id"]),
                    comparison_filing_id=uuid.UUID(state["comparison_filing_id"]),
                )
            except FilingComparisonError as exc:
                raise WorkflowError("validation_error", exc.code, exc.message) from exc
            await service.process_comparison(result.comparison_id)
            comparison = await self.comparisons.get_comparison(result.comparison_id)
            if comparison is None or comparison.status != "completed":
                raise WorkflowError(
                    "recoverable_database_error",
                    "comparison_not_completed",
                    "Disclosure comparison did not complete.",
                )
            changes = await self.comparisons.list_changes(result.comparison_id, limit=1000)
            await self.workflow.set_run_status(
                await self._require_run(uuid.UUID(state["analysis_run_id"])),
                "comparing_disclosures",
                comparison_id=result.comparison_id,
                metrics={"disclosure_changes": len(changes)},
            )
            return {
                "comparison_id": str(result.comparison_id),
                "disclosure_change_ids": [str(change.id) for change in changes],
                "comparison_complete": True,
                "counts": {**state.get("counts", {}), "disclosure_changes": len(changes)},
            }

        return await self._node("run_disclosure_comparison", state, "comparing_disclosures", work)

    async def _extract_financial_claims(self, state: AnalysisState) -> AnalysisState:
        async def work() -> AnalysisState:
            claims = await self.financial.list_claims(
                comparison_id=uuid.UUID(str(state["comparison_id"])),
                limit=1000,
            )
            return {
                "financial_claim_ids": [str(claim.id) for claim in claims],
                "counts": {**state.get("counts", {}), "financial_claims_existing": len(claims)},
            }

        return await self._node("extract_financial_claims", state, "extracting_claims", work)

    async def _verify_financial_claims(self, state: AnalysisState) -> AnalysisState:
        async def work() -> AnalysisState:
            service = FinancialVerificationService(self.session, self.settings)
            metrics = await service.verify_claims_for_comparison(
                uuid.UUID(str(state["comparison_id"]))
            )
            verifications = await self.financial.list_verifications(
                comparison_id=uuid.UUID(str(state["comparison_id"]))
            )
            claims = await self.financial.list_claims(
                comparison_id=uuid.UUID(str(state["comparison_id"])),
                limit=1000,
            )
            counts = _count_by(verifications, "verification_status")
            return {
                "financial_claim_ids": [str(claim.id) for claim in claims],
                "claim_verification_ids": [str(item.id) for item in verifications],
                "financial_verification_complete": True,
                "counts": {
                    **state.get("counts", {}),
                    "financial_verification": counts,
                    "financial_verification_metrics": metrics,
                },
            }

        return await self._node("verify_financial_claims", state, "verifying_claims", work)

    async def _analyze_contradictions(self, state: AnalysisState) -> AnalysisState:
        async def work() -> AnalysisState:
            service = ContradictionAnalysisService(self.session, self.settings)
            metrics = await service.analyze_comparison(uuid.UUID(str(state["comparison_id"])))
            findings = await self.contradictions.list_findings(
                comparison_id=uuid.UUID(str(state["comparison_id"])),
                limit=1000,
            )
            return {
                "contradiction_finding_ids": [str(item.id) for item in findings],
                "contradiction_analysis_complete": True,
                "counts": {
                    **state.get("counts", {}),
                    "contradictions": _count_by(findings, "contradiction_type"),
                    "contradiction_metrics": metrics,
                },
            }

        return await self._node(
            "analyze_contradictions",
            state,
            "analyzing_contradictions",
            work,
        )

    async def _validate_evidence(self, state: AnalysisState) -> AnalysisState:
        async def work() -> AnalysisState:
            warnings = list(state.get("warnings", []))
            blocking = []
            comparison_id = uuid.UUID(str(state["comparison_id"]))
            changes = await self.comparisons.list_changes(comparison_id, limit=1000)
            for change in changes:
                if not (change.previous_text or change.current_text):
                    warnings.append(f"Disclosure change {change.id} has no source passage text.")
            verifications = await self.financial.list_verifications(comparison_id=comparison_id)
            for verification in verifications:
                if verification.verification_status == "contradicted" and not verification.formula:
                    blocking.append(f"Verification {verification.id} lacks a formula.")
            findings = await self.contradictions.list_findings(
                comparison_id=comparison_id,
                limit=1000,
            )
            for finding in findings:
                evidence = await self.contradictions.list_evidence(finding.id)
                if not any(item.evidence_role == "primary" for item in evidence):
                    blocking.append(f"Finding {finding.id} lacks primary evidence.")
            if blocking:
                raise WorkflowError(
                    "evidence_validation_error",
                    "blocking_evidence_failures",
                    "Evidence validation found blocking failures.",
                )
            coverage = {
                "disclosure_changes_checked": len(changes),
                "verifications_checked": len(verifications),
                "contradictions_checked": len(findings),
            }
            return {
                "evidence_valid": True,
                "warnings": warnings,
                "counts": {**state.get("counts", {}), "evidence_coverage": coverage},
            }

        return await self._node("validate_evidence", state, "validating_evidence", work)

    async def _prioritize_findings(self, state: AnalysisState) -> AnalysisState:
        async def work() -> AnalysisState:
            findings = await self.contradictions.list_findings(
                comparison_id=uuid.UUID(str(state["comparison_id"])),
                limit=1000,
            )
            priorities = {}
            for finding in findings:
                priorities[str(finding.id)] = _review_priority(finding)
            requires_review, reason = self._review_policy(findings)
            run = await self._require_run(uuid.UUID(state["analysis_run_id"]))
            await self.workflow.set_run_status(
                run,
                "validating_evidence",
                requires_human_review=requires_review,
                review_gate_reason=reason,
                metrics={"review_priorities": priorities},
            )
            return {
                "requires_human_review": requires_review,
                "counts": {**state.get("counts", {}), "review_priorities": priorities},
            }

        return await self._node("prioritize_findings", state, "validating_evidence", work)

    async def _review_gate(self, state: AnalysisState) -> AnalysisState:
        async def work() -> AnalysisState:
            if not state.get("requires_human_review"):
                return {"workflow_status": "generating_report"}
            run = await self._require_run(uuid.UUID(state["analysis_run_id"]))
            findings = await self.contradictions.list_findings(
                comparison_id=uuid.UUID(str(state["comparison_id"])),
                limit=1000,
            )
            review = await self.workflow.create_review_request(
                analysis_run_id=run.id,
                review_type="contradiction_review",
                reason=json_safe(run.review_gate_reason).get("reason", "Review policy required."),
                finding_ids=[
                    finding.id
                    for finding in findings
                    if _review_priority(finding) != "informational"
                ],
                claim_ids=[],
                verification_ids=[],
            )
            await self.workflow.set_run_status(
                run,
                "awaiting_human_review",
                current_node="review_gate",
                requires_human_review=True,
            )
            await self.workflow.add_event(
                analysis_run_id=run.id,
                event_type="review_requested",
                node_name="review_gate",
                event_payload={"review_request_id": str(review.id), "reason": review.reason},
            )
            await self.workflow.add_event(
                analysis_run_id=run.id,
                event_type="workflow_interrupted",
                node_name="review_gate",
                event_payload={"review_request_id": str(review.id)},
            )
            await self.session.commit()
            review_result = interrupt(
                {
                    "analysis_run_id": str(run.id),
                    "review_request_id": str(review.id),
                    "reason": review.reason,
                }
            )
            return {
                "review_request_id": str(review.id),
                "review_result": review_result,
                "workflow_status": "generating_report",
            }

        return await self._node("review_gate", state, "awaiting_human_review", work)

    async def _generate_report(self, state: AnalysisState) -> AnalysisState:
        async def work() -> AnalysisState:
            report = await AnalysisReportService(self.session, self.settings).generate_report(
                uuid.UUID(state["analysis_run_id"])
            )
            await self.workflow.add_event(
                analysis_run_id=uuid.UUID(state["analysis_run_id"]),
                event_type="report_generated",
                node_name="generate_report",
                event_payload={"report_id": str(report.id), "content_hash": report.content_hash},
            )
            return {"report_id": str(report.id), "workflow_status": "generating_report"}

        return await self._node("generate_report", state, "generating_report", work)

    async def _finalize_analysis(self, state: AnalysisState) -> AnalysisState:
        async def work() -> AnalysisState:
            run = await self._require_run(uuid.UUID(state["analysis_run_id"]))
            status = "completed_with_warnings" if state.get("warnings") else "completed"
            await self.workflow.set_run_status(
                run,
                status,
                current_node=None,
                metrics={
                    "completed_nodes": _append_node(
                        state.get("completed_nodes", []),
                        "finalize_analysis",
                    ),
                    "warnings": state.get("warnings", []),
                },
            )
            await self.workflow.add_event(
                analysis_run_id=run.id,
                event_type="workflow_completed",
                node_name="finalize_analysis",
                event_payload={"status": status},
            )
            return {"workflow_status": status}

        return await self._node("finalize_analysis", state, "completed", work)

    async def _node(
        self,
        node_name: str,
        state: AnalysisState,
        status: str,
        work,
    ) -> AnalysisState:
        run = await self._require_run(uuid.UUID(state["analysis_run_id"]))
        if run.status == "cancelled":
            return {"workflow_status": "cancelled"}
        started = time.perf_counter()
        attempt = 1
        await self.workflow.set_run_status(run, status, current_node=node_name)
        await self.workflow.add_event(
            analysis_run_id=run.id,
            event_type="node_started",
            node_name=node_name,
            attempt_number=attempt,
            event_payload={"status": status},
        )
        await self.session.flush()
        try:
            result = await work()
            duration_ms = int((time.perf_counter() - started) * 1000)
            completed_nodes = _append_node(state.get("completed_nodes", []), node_name)
            result = {**result, "completed_nodes": completed_nodes}
            await self.workflow.add_event(
                analysis_run_id=run.id,
                event_type="node_completed",
                node_name=node_name,
                attempt_number=attempt,
                event_payload={"outputs": _compact_outputs(result)},
                duration_ms=duration_ms,
            )
            run.processing_metrics = {
                **(run.processing_metrics or {}),
                "completed_nodes": completed_nodes,
                "last_node_duration_ms": {node_name: duration_ms},
            }
            await self.session.flush()
            return result
        except WorkflowError as exc:
            exc.node = exc.node or node_name
            await self.workflow.add_event(
                analysis_run_id=run.id,
                event_type="node_failed",
                node_name=node_name,
                attempt_number=attempt,
                event_payload={"category": exc.category, "code": exc.code},
            )
            raise

    async def _fail_run(self, analysis_run_id: uuid.UUID, exc: WorkflowError) -> None:
        run = await self._require_run(analysis_run_id)
        await self.workflow.set_run_status(
            run,
            "failed",
            current_node=None,
            failure_code=exc.code,
            failure_message=exc.public_message,
            failure_node=exc.node,
        )
        await self.session.commit()

    async def _require_run(self, analysis_run_id: uuid.UUID) -> AnalysisRun:
        run = await self.workflow.get_run(analysis_run_id)
        if run is None:
            raise WorkflowError("validation_error", "analysis_not_found", "Analysis run not found.")
        return run

    async def _filing_pair(self, state: AnalysisState) -> tuple[Filing, Filing]:
        current = await self.filings.get(uuid.UUID(state["current_filing_id"]))
        previous = await self.filings.get(uuid.UUID(state["comparison_filing_id"]))
        if current is None or previous is None:
            raise WorkflowError("validation_error", "filing_not_found", "Both filings must exist.")
        return current, previous

    async def _has_processing_ready(self, filing_id: uuid.UUID) -> bool:
        section_count = await self.session.scalar(
            select(func.count())
            .select_from(FilingSection)
            .where(FilingSection.filing_id == filing_id)
        )
        chunk_count = await self.session.scalar(
            select(func.count())
            .select_from(FilingChunk)
            .join(FilingSection)
            .where(FilingSection.filing_id == filing_id)
        )
        embedded_chunk_count = await self.session.scalar(
            select(func.count())
            .select_from(FilingChunk)
            .join(FilingSection)
            .where(
                FilingSection.filing_id == filing_id,
                FilingChunk.embedding.is_not(None),
            )
        )
        return bool(section_count and chunk_count and chunk_count == embedded_chunk_count)

    def _review_policy(
        self,
        findings: list[ContradictionFinding],
    ) -> tuple[bool, dict[str, object]]:
        if self.settings.workflow_require_review_for_all_contradictions and findings:
            return True, {"reason": "Policy requires review for all contradiction candidates."}
        min_severity = SEVERITY_ORDER[self.settings.workflow_review_min_severity]
        for finding in findings:
            if finding.contradiction_type == "numerical_claim_contradiction":
                return True, {"reason": "Numerical contradiction candidate requires review."}
            if SEVERITY_ORDER[finding.severity] >= min_severity:
                return True, {"reason": "Finding severity meets workflow review threshold."}
            if Decimal(str(finding.confidence)) < Decimal(
                str(self.settings.workflow_review_low_confidence_threshold)
            ):
                return True, {"reason": "Finding confidence is below publication threshold."}
        return False, {"reason": "No workflow-level review policy triggered."}


async def create_workflow_checkpointer(settings: Settings):
    if settings.workflow_checkpoint_provider == "postgres":
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL LangGraph checkpointing requires "
                "langgraph-checkpoint-postgres."
            ) from exc
        checkpoint_url = _checkpoint_database_url(settings)
        if checkpoint_url not in _POSTGRES_CHECKPOINTERS:
            pool = AsyncConnectionPool(
                checkpoint_url,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                min_size=1,
                max_size=4,
                open=False,
            )
            await pool.open()
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            _POSTGRES_CHECKPOINTERS[checkpoint_url] = saver
        return _POSTGRES_CHECKPOINTERS[checkpoint_url]
    from langgraph.checkpoint.memory import MemorySaver

    global _MEMORY_CHECKPOINTER
    if _MEMORY_CHECKPOINTER is None:
        _MEMORY_CHECKPOINTER = MemorySaver()
    return _MEMORY_CHECKPOINTER


def _checkpoint_conninfo(url: str) -> str:
    return (
        url.replace("postgresql+psycopg://", "postgresql://", 1)
        .replace("postgresql+asyncpg://", "postgresql://", 1)
        .replace("ssl=require", "sslmode=require")
    )


def _checkpoint_database_url(settings: Settings) -> str:
    return _checkpoint_conninfo(settings.database_url)


def _review_route(state: AnalysisState) -> Literal["generate_report", "end"]:
    if state.get("workflow_status") == "cancelled":
        return "end"
    return "generate_report"


def _review_priority(finding: ContradictionFinding) -> str:
    if finding.severity == "critical":
        return "urgent"
    if finding.severity == "high":
        return "high"
    if finding.severity == "medium":
        return "normal"
    return "informational"


def _count_by(items: list[object], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(getattr(item, attr))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _append_node(nodes: list[str], node_name: str) -> list[str]:
    if node_name in nodes:
        return nodes
    return [*nodes, node_name]


def _completed_nodes(metrics: dict[str, object]) -> list[str]:
    values = metrics.get("completed_nodes", [])
    return [str(value) for value in values] if isinstance(values, list) else []


def _compact_outputs(result: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in result.items()
        if key.endswith("_id")
        or key.endswith("_ids")
        or key in {"counts", "workflow_status", "requires_human_review", "evidence_valid"}
    }


def _provider_error_message(exc: ProviderRequestError) -> str:
    parts = [f"{exc.provider} request failed", f"category={exc.error_category}"]
    if exc.model:
        parts.append(f"model={exc.model}")
    if exc.status_code is not None:
        parts.append(f"status={exc.status_code}")
    parts.append(f"retries={exc.retry_count}")
    if exc.retry_after_seconds is not None:
        parts.append(f"retry_after={exc.retry_after_seconds:.0f}s")
    return " ".join(parts)


def json_safe(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}

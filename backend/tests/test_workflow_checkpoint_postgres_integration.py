from __future__ import annotations

from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import text

from app.core.config import Settings
from app.db.models import Filing
from app.repositories.workflow_repository import WorkflowRepository
from app.services.analysis_workflow_service import create_workflow_checkpointer
from tests.integration_helpers import create_comparison_corpus

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


class CheckpointProbeState(TypedDict, total=False):
    analysis_run_id: str
    expensive_count: int
    review_result: dict[str, object]
    completed: bool


@pytest.mark.asyncio
async def test_postgres_checkpointer_persists_interrupt_and_resumes_same_thread(
    integration_session,
    test_database_url: str,
) -> None:
    corpus = await create_comparison_corpus(integration_session)
    current = await integration_session.get(Filing, corpus["current_filing_id"])
    previous = await integration_session.get(Filing, corpus["comparison_filing_id"])
    assert current is not None
    assert previous is not None
    repo = WorkflowRepository(integration_session)
    run, _ = await repo.create_or_get_run(
        current_filing=current,
        comparison_filing=previous,
        workflow_version="checkpoint-test-v1",
        graph_version="checkpoint-probe-v1",
    )
    await integration_session.commit()

    settings = Settings(
        app_profile="local-cloud",
        database_url=test_database_url,
        workflow_checkpoint_provider="postgres",
    )
    config = {"configurable": {"thread_id": run.checkpoint_thread_id}}
    checkpointer = await create_workflow_checkpointer(settings)
    first_graph = _compile_checkpoint_probe(checkpointer)

    interrupted = await first_graph.ainvoke(
        {"analysis_run_id": str(run.id), "expensive_count": 0},
        config=config,
    )
    assert "__interrupt__" in interrupted

    checkpoint_count = await integration_session.scalar(
        text("select count(*) from checkpoints where thread_id = :thread_id"),
        {"thread_id": run.checkpoint_thread_id},
    )
    assert checkpoint_count and checkpoint_count > 0

    recreated_graph = _compile_checkpoint_probe(checkpointer)
    resumed = await recreated_graph.ainvoke(
        Command(resume={"decision": "approved", "reviewer": "integration-test"}),
        config=config,
    )

    assert resumed["completed"] is True
    assert resumed["review_result"]["decision"] == "approved"
    assert resumed["expensive_count"] == 1
    assert "checkpoint_thread_id" not in str(resumed)


def _compile_checkpoint_probe(checkpointer):
    graph = StateGraph(CheckpointProbeState)

    async def expensive_node(state: CheckpointProbeState) -> CheckpointProbeState:
        return {"expensive_count": state.get("expensive_count", 0) + 1}

    async def review_gate(state: CheckpointProbeState) -> CheckpointProbeState:
        result = interrupt(
            {
                "analysis_run_id": state["analysis_run_id"],
                "review_type": "checkpoint_probe",
            }
        )
        return {"review_result": result}

    async def finalize(_state: CheckpointProbeState) -> CheckpointProbeState:
        return {"completed": True}

    graph.add_node("expensive_node", expensive_node)
    graph.add_node("review_gate", review_gate)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "expensive_node")
    graph.add_edge("expensive_node", "review_gate")
    graph.add_edge("review_gate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)

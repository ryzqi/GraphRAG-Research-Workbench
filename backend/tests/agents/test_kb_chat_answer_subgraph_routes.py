from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.kb_chat_agentic import answer_subgraph
from app.agents.kb_chat_agentic.tool_loop import force_exit_node
from app.core.settings import Settings


def _build_fuse_state(
    *,
    citation_run: dict[str, object],
    answer_run: dict[str, object],
    generation_retries: int = 0,
    total_rounds: int = 1,
    retrieval_retries: int = 0,
) -> dict[str, object]:
    return {
        "loop_counts": {
            "total_rounds": total_rounds,
            "retrieval_retries": retrieval_retries,
            "generation_retries": generation_retries,
        },
        "draft_answer": "CoT 更适合单路径、步骤明确的推理任务。[S1]",
        "final_answer": "CoT 更适合单路径、步骤明确的推理任务。[S1]",
        "stage_summaries": {},
        "answer_review_runs": [citation_run, answer_run],
        "reflection": {},
    }


def _build_passed_run(*, check: str) -> dict[str, object]:
    return {
        "review_round": 0,
        "check": check,
        "passed": True,
        "reason": "passed",
        "confidence": 1.0,
        "details": {
            "paragraph_review_counts": {"total": 1, "passed": 1, "failed": 0},
            "repair_target_count": 0,
            "unsupported_scope": "none",
        },
        "affected_paragraph_ids": [],
    }


@pytest.mark.asyncio
async def test_answer_review_fuse_routes_passed_paragraphs_to_answer_commit() -> None:
    state = _build_fuse_state(
        citation_run=_build_passed_run(check="citation"),
        answer_run=_build_passed_run(check="answer"),
    )

    command = await answer_subgraph._answer_review_fuse(
        state,
        SimpleNamespace(),
        settings=Settings(),
    )

    assert command.goto == "answer_commit"
    assert command.update["reflection"]["review_passed"] is True
    assert command.update["reflection"]["action"] == "none"
    assert command.update["stage_summaries"]["answer_review"]["reason"] == "passed"


@pytest.mark.asyncio
async def test_answer_review_fuse_routes_auxiliary_only_unsupported_to_answer_repair() -> None:
    state = _build_fuse_state(
        citation_run=_build_passed_run(check="citation"),
        answer_run={
            "review_round": 0,
            "check": "answer",
            "passed": False,
            "reason": "unsupported_claims",
            "confidence": 0.92,
            "details": {
                "paragraph_review_counts": {"total": 1, "passed": 0, "failed": 1},
                "repair_target_count": 1,
                "unsupported_scope": "auxiliary_only",
            },
            "affected_paragraph_ids": ["p1"],
        },
    )

    command = await answer_subgraph._answer_review_fuse(
        state,
        SimpleNamespace(),
        settings=Settings(),
    )

    assert command.goto == "answer_repair"
    assert command.update["reflection"]["review_passed"] is False
    assert command.update["stage_summaries"]["answer_review"]["repair_target_count"] == 1
    assert (
        command.update["stage_summaries"]["answer_review"]["unsupported_scope_summary"]
        == "auxiliary_only"
    )


@pytest.mark.asyncio
async def test_main_claim_failure_flows_from_fuse_commit_to_transform_query() -> None:
    fuse_state = _build_fuse_state(
        citation_run=_build_passed_run(check="citation"),
        answer_run={
            "review_round": 0,
            "check": "answer",
            "passed": False,
            "reason": "unsupported_claims",
            "confidence": 0.92,
            "details": {
                "paragraph_review_counts": {"total": 1, "passed": 0, "failed": 1},
                "repair_target_count": 1,
                "unsupported_scope": "main",
            },
            "affected_paragraph_ids": ["p1"],
        },
    )

    fuse_command = await answer_subgraph._answer_review_fuse(
        fuse_state,
        SimpleNamespace(),
        settings=Settings(),
    )

    assert fuse_command.goto == "answer_commit"
    assert fuse_command.update["reflection"]["review_passed"] is False
    assert fuse_command.update["reflection"]["reason"] == "unsupported_claims"

    commit_updates = await answer_subgraph._answer_commit(
        {
            **fuse_state,
            **fuse_command.update,
        },
        SimpleNamespace(),
        settings=Settings(),
    )

    assert commit_updates["reflection"]["action"] == "transform_query"
    assert commit_updates["stage_summaries"]["answer_subgraph"]["next_step"] == "transform_query"
    assert (
        commit_updates["routing_decisions"]["answer_subgraph"]["next_node"]
        == "transform_query"
    )


@pytest.mark.asyncio
async def test_missing_paragraph_citations_route_to_answer_repair_when_safe() -> None:
    citation_state = {
        "user_input": "请说明 CoT 的适用场景。",
        "draft_answer": "CoT 更适合单路径、步骤明确的推理任务。",
        "final_context": "[S1] CoT 适合单路径、步骤明确的推理任务。",
        "citation_catalog": {
            "S1": {
                "citation_id": "S1",
                "excerpt": "evidence for S1",
            }
        },
        "loop_counts": {
            "total_rounds": 1,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
        "stage_summaries": {},
        "answer_paragraphs": [
            {
                "paragraph_id": "p1",
                "text": "CoT 更适合单路径、步骤明确的推理任务。",
                "citation_ids": [],
                "claims": [
                    {
                        "claim_id": "c1",
                        "claim_text": "CoT 更适合单路径、步骤明确的推理任务。",
                        "role": "main",
                        "support_status": "supported",
                        "supporting_citation_ids": ["S1"],
                    }
                ],
                "review_status": "failed",
            }
        ],
    }

    citation_updates = await answer_subgraph._answer_review_citation(
        citation_state,
        SimpleNamespace(chat_model=None),
        settings=Settings(),
    )
    citation_run = citation_updates["answer_review_runs"][0]

    assert citation_run["reason"] == "missing_citations"

    fuse_state = {
        **citation_state,
        "answer_review_runs": [
            citation_run,
            _build_passed_run(check="answer"),
        ],
        "reflection": {},
    }

    fuse_command = await answer_subgraph._answer_review_fuse(
        fuse_state,
        SimpleNamespace(),
        settings=Settings(),
    )

    assert fuse_command.goto == "answer_repair"
    assert fuse_command.update["reflection"]["reason"] == "missing_citations"
    assert fuse_command.update["stage_summaries"]["answer_review"]["repair_target_count"] == 1


@pytest.mark.asyncio
async def test_answer_commit_promotes_existing_final_answer_to_best_answer_before_force_exit() -> None:
    state = {
        "loop_counts": {
            "total_rounds": 1,
            "retrieval_retries": 0,
            "generation_retries": 1,
        },
        "answer_subgraph_state": {
            "repair_attempts": 1,
        },
        "draft_answer": "AI Agent 的 Tool Use / Function Calling 六步完整流程是任务判断、工具选择、参数准备、工具调用、结果获取与处理、结果整合与下一步规划。[S1]",
        "final_answer": "AI Agent 的 Tool Use / Function Calling 六步完整流程是任务判断、工具选择、参数准备、工具调用、结果获取与处理、结果整合与下一步规划。[S1]",
        "stage_summaries": {},
        "reflection": {
            "review_passed": False,
            "reason": "missing_citations",
            "action": "transform_query",
        },
    }

    commit_updates = await answer_subgraph._answer_commit(
        state,
        SimpleNamespace(),
        settings=Settings(),
    )

    assert (
        commit_updates["routing_decisions"]["answer_subgraph"]["next_node"]
        == "force_exit"
    )
    assert commit_updates["best_answer"] == state["final_answer"]
    assert commit_updates["best_answer_meta"]["from_node"] == "answer_commit"

    force_exit_updates = force_exit_node(
        {
            **state,
            **commit_updates,
        },
        settings=Settings(),
    )

    assert force_exit_updates["final_answer"] == state["final_answer"]
    assert force_exit_updates["stage_summaries"]["force_exit"]["used_best_answer"] is True

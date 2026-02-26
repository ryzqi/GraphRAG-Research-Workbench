from __future__ import annotations

import types

import pytest
from langgraph.types import Command

from app.agents.kb_chat_agentic.answer_subgraph import (
    _answer_commit,
    _answer_review_fuse,
    build_answer_subgraph,
)


class _DummyChatModel:
    pass


def _collect_targets(graph_json: dict, source: str) -> set[str]:
    edges = graph_json.get("edges")
    if not isinstance(edges, list):
        return set()
    targets: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("source") != source:
            continue
        target = edge.get("target")
        if isinstance(target, str) and target:
            targets.add(target)
    return targets


def test_answer_subgraph_topology_contains_repair_loop():
    settings = types.SimpleNamespace(
        kb_chat_max_generation_retries=1,
        kb_chat_max_total_rounds=3,
        kb_chat_max_retrieval_retries=2,
    )
    compiled = build_answer_subgraph(settings=settings, chat_model=_DummyChatModel())
    graph_json = compiled.get_graph().to_json()

    assert _collect_targets(graph_json, "draft_generate") == {"answer_review_dispatch"}
    assert _collect_targets(graph_json, "answer_review_dispatch") >= {
        "answer_review_citation",
        "answer_review_factual",
        "answer_review_answerability",
        "answer_review_fuse",
    }
    assert _collect_targets(graph_json, "answer_review_citation") == {"answer_review_fuse"}
    assert _collect_targets(graph_json, "answer_review_factual") == {"answer_review_fuse"}
    assert _collect_targets(graph_json, "answer_review_answerability") == {"answer_review_fuse"}
    assert _collect_targets(graph_json, "answer_review_fuse") == {
        "answer_commit",
        "answer_repair",
    }
    assert _collect_targets(graph_json, "answer_repair") == {"answer_review_dispatch"}
    assert _collect_targets(graph_json, "answer_commit") == {"__end__"}


@pytest.mark.asyncio
async def test_answer_commit_marks_force_exit_when_generation_budget_exhausted():
    settings = types.SimpleNamespace(
        kb_chat_max_generation_retries=1,
        kb_chat_max_total_rounds=3,
        kb_chat_max_retrieval_retries=2,
    )
    state = {
        "reflection": {"review_passed": False, "reason": "missing_citations"},
        "loop_counts": {"total_rounds": 1, "retrieval_retries": 0, "generation_retries": 1},
        "draft_answer": "draft",
        "stage_summaries": {},
    }

    updates = await _answer_commit(state, object(), settings=settings)

    assert updates["reflection"]["action"] == "force_exit"
    assert updates["degrade_reason"] == "max_generation_retries"
    assert updates["stage_summaries"]["answer_subgraph"]["next_step"] == "force_exit"


@pytest.mark.asyncio
async def test_answer_review_fuse_populates_breakdown_and_routes_to_repair():
    settings = types.SimpleNamespace(
        kb_chat_grader_fail_policy="closed",
        kb_chat_max_generation_retries=1,
        kb_chat_max_total_rounds=3,
        kb_chat_max_retrieval_retries=2,
    )
    state = {
        "loop_counts": {"total_rounds": 1, "retrieval_retries": 0, "generation_retries": 0},
        "draft_answer": "答案正文[S1]",
        "final_context": "[S1] 支持证据",
        "answer_review_runs": [
            {
                "check": "citation",
                "passed": False,
                "reason": "missing_citations",
                "confidence": 0.88,
                "fallback_reason": None,
                "decision_source": "rule",
            },
            {
                "check": "factual",
                "passed": True,
                "reason": "passed",
                "confidence": 0.91,
                "fallback_reason": None,
                "decision_source": "llm",
            },
            {
                "check": "answerability",
                "passed": True,
                "reason": "passed",
                "confidence": 0.74,
                "fallback_reason": None,
                "decision_source": "llm",
            },
        ],
        "reflection": {},
        "stage_summaries": {},
    }

    result = await _answer_review_fuse(state, object(), settings=settings)

    assert isinstance(result, Command)
    assert result.goto == "answer_repair"
    assert isinstance(result.update, dict)
    reflection = result.update["reflection"]
    assert reflection["review_passed"] is False
    assert reflection["reason"] == "missing_citations"
    assert reflection["action"] == "transform_query"
    assert isinstance(reflection.get("review_breakdown"), dict)
    assert reflection["review_breakdown"]["citation"]["passed"] is False
    summary = result.update["stage_summaries"]["answer_review"]
    assert summary["passed"] is False
    assert summary["review_risk_level"] == "high"

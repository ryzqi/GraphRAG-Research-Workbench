from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.kb_chat_agentic.answer_subgraph import _answer_commit
from app.agents.kb_chat_agentic.preprocess import prepare_messages
from app.agents.kb_chat_agentic.reflection import route_after_answer_review
from app.agents.kb_chat_agentic.tool_loop import force_exit_node
from app.agents.kb_chat_agentic_graph import _route_after_preprocess_subgraph
from app.agents.preprocess_subgraph import _route_after_ambiguity


def _settings(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "app_env": "test",
        "kb_chat_json_safe_policy": "stringify",
        "kb_chat_parallel_retrieval_min_queries": 2,
        "kb_chat_parallel_retrieval_max_branches": 6,
        "kb_chat_parallel_retrieval_include_main": True,
        "kb_chat_max_generation_retries": 2,
        "kb_chat_max_retrieval_retries": 2,
        "kb_chat_max_total_rounds": 3,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(
        context={
            "runtime_config": {},
            "kb_ids": [],
            "thread_id": "thread-test",
            "user_id": "user-test",
        },
        store=None,
    )


@pytest.mark.asyncio
async def test_prepare_messages_writes_preprocess_routing_decision() -> None:
    command = await prepare_messages(
        {
            "user_input": "主问题",
            "normalized_query": "主问题",
            "query_strategy": "direct",
            "stage_summaries": {},
        },
        runtime=_runtime(),
        settings=_settings(),
    )

    assert command.goto == "dispatch_subqueries"
    assert command.update["routing_decisions"]["preprocess"]["next_node"] == "retrieval_subgraph"
    assert command.update["routing_decisions"]["preprocess"]["decision_source"] == "prepare_messages"
    assert "preprocess_next" not in command.update


def test_route_after_preprocess_subgraph_prefers_routing_decision() -> None:
    state = {
        "routing_decisions": {
            "preprocess": {
                "next_node": "retrieval_subgraph",
            }
        },
        "reflection": {"action": "transform_query"},
        "preprocess_next": "force_exit",
        "clarification_payload": {"question": "stale"},
    }

    assert _route_after_preprocess_subgraph(state) == "retrieval_subgraph"


def test_route_after_preprocess_subgraph_ignores_legacy_fallback_fields_when_routing_missing() -> None:
    state = {
        "reflection": {"action": "transform_query"},
        "preprocess_next": "force_exit",
        "clarification_payload": {"question": "stale"},
    }

    assert _route_after_preprocess_subgraph(state) == "retrieval_subgraph"


def test_route_after_ambiguity_ignores_legacy_reflection_action_when_routing_missing() -> None:
    state = {
        "reflection": {"action": "clarify"},
    }

    assert _route_after_ambiguity(state) == "query_normalize"


@pytest.mark.asyncio
async def test_answer_commit_writes_answer_subgraph_routing_decision() -> None:
    result = await _answer_commit(
        {
            "loop_counts": {
                "total_rounds": 0,
                "retrieval_retries": 0,
                "generation_retries": 0,
            },
            "reflection": {
                "review_passed": True,
                "reason": "passed",
                "review_confidence": 0.9,
            },
            "draft_answer": "最终答案 [S1]",
            "final_answer": "最终答案 [S1]",
            "answer_subgraph_state": {"repair_attempts": 0},
            "stage_summaries": {},
        },
        runtime=None,
        settings=_settings(),
    )

    assert result["routing_decisions"]["answer_subgraph"]["next_node"] == "END"
    assert result["routing_decisions"]["answer_subgraph"]["decision_source"] == "answer_commit"


def test_route_after_answer_review_prefers_routing_decision() -> None:
    state = {
        "routing_decisions": {
            "answer_subgraph": {
                "next_node": "END",
            }
        },
        "reflection": {
            "review_passed": False,
            "reason": "missing_citations",
        },
    }

    assert route_after_answer_review(state, _settings()) == "END"


def test_route_after_answer_review_ignores_legacy_reflection_when_routing_missing() -> None:
    state = {
        "reflection": {
            "review_passed": True,
            "reason": "passed",
        },
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
    }

    assert route_after_answer_review(state, _settings()) == "transform_query"


def test_force_exit_node_prefers_canonical_routing_reason() -> None:
    result = force_exit_node(
        {
            "routing_decisions": {
                "answer_subgraph": {
                    "next_node": "force_exit",
                    "action": "force_exit",
                    "reason": "severe_conflict",
                    "decision_source": "answer_commit",
                }
            },
            "reflection": {
                "action": "none",
                "reason": "passed",
                "review_passed": True,
            },
            "final_answer": "stale answer",
            "draft_answer": "stale answer",
            "best_answer": "候选答案 [S1]",
            "stage_summaries": {},
        },
        _settings(),
    )

    assert result["final_answer"] == "候选答案 [S1]"
    assert result["reflection"]["reason"] == "severe_conflict"
    assert result["stage_summaries"]["force_exit"]["reason"] == "severe_conflict"
    assert result["stage_summaries"]["force_exit"]["review_passed"] is False


def test_force_exit_node_uses_canonical_clarify_route() -> None:
    result = force_exit_node(
        {
            "routing_decisions": {
                "preprocess": {
                    "next_node": "force_exit",
                    "action": "clarify",
                    "reason": "ambiguous_query",
                    "decision_source": "ambiguity_check",
                }
            },
            "reflection": {"action": "none", "reason": "passed"},
            "clarification_payload": {"question": "请补充时间范围"},
            "stage_summaries": {},
        },
        _settings(),
    )

    assert result["final_answer"] == "请补充时间范围"
    assert result["reflection"]["action"] == "clarify"
    assert result["stage_summaries"]["force_exit"]["reason"] == "clarify"

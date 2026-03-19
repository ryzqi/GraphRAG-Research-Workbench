from __future__ import annotations

import importlib

from types import SimpleNamespace

import pytest

from app.agents.kb_chat_agentic.answer_subgraph import _answer_commit
from app.agents.kb_chat_agentic.reflection import (
    dispatch_subqueries,
    route_after_answer_review,
    transform_query_for_retry,
)
from app.agents.kb_chat_agentic.tool_loop import force_exit_node
from app.agents.kb_chat_agentic_graph import _route_after_preprocess_subgraph
from app.agents.kb_chat_trace_nodes import KB_CHAT_NODE_METADATA
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


def _query_plan_callable():
    preprocess_module = importlib.import_module("app.agents.kb_chat_agentic.preprocess")
    query_plan = getattr(preprocess_module, "query_plan", None)
    assert callable(query_plan), "query_plan should exist in app.agents.kb_chat_agentic.preprocess"
    return query_plan


@pytest.mark.asyncio
async def test_query_plan_writes_preprocess_routing_decision() -> None:
    query_plan = _query_plan_callable()
    command = await query_plan(
        {
            "user_input": "主问题",
            "normalized_query": "主问题",
            "normalized_meta": {"recall_risk": "low"},
            "stage_summaries": {},
        },
        runtime=_runtime(),
        settings=_settings(),
    )

    assert command.goto == "dispatch_subqueries"
    assert command.update["routing_decisions"]["preprocess"]["next_node"] == "retrieval_subgraph"
    assert command.update["routing_decisions"]["preprocess"]["decision_source"] == "query_plan"
    assert "preprocess_next" not in command.update


def test_query_plan_node_label_is_query_focused() -> None:
    assert KB_CHAT_NODE_METADATA["query_plan"]["label"] == "查询规划"
    assert "prepare_messages" not in KB_CHAT_NODE_METADATA


@pytest.mark.asyncio
async def test_query_plan_rejects_fragment_like_expansion_and_records_reason() -> None:
    query_plan = _query_plan_callable()
    command = await query_plan(
        {
            "user_input": "解释agent的记忆系统",
            "normalized_query": "解释agent的记忆系统",
            "normalized_meta": {
                "recall_risk": "high",
                "drift_risk": False,
                "constraint_preserved": True,
            },
            "stage_summaries": {},
        },
        runtime=_runtime(),
        settings=_settings(),
    )

    query_texts = [
        str(item.get("query") or "")
        for item in command.update["query_items"]
        if isinstance(item, dict)
    ]
    assert query_texts == ["解释agent的记忆系统"]
    assert command.update["query_plan_diagnostics"]["rejection_counts"]["fragment_rejected"] >= 1


@pytest.mark.asyncio
async def test_dispatch_subqueries_prefers_planner_quality_score_order() -> None:
    command = await dispatch_subqueries(
        {
            "query_strategy": "paraphrase",
            "query_items": [
                {
                    "kind": "paraphrase",
                    "query": "低质量候选",
                    "index": 0,
                    "quality_score": 0.11,
                    "use_dense": True,
                    "use_bm25": True,
                },
                {
                    "kind": "paraphrase",
                    "query": "高质量候选",
                    "index": 1,
                    "quality_score": 0.97,
                    "use_dense": True,
                    "use_bm25": True,
                },
            ],
            "stage_summaries": {},
        },
        runtime=_runtime(),
        settings=_settings(
            kb_chat_parallel_retrieval_min_queries=1,
            kb_chat_parallel_retrieval_max_branches=2,
        ),
    )

    dispatched_queries = [task.arg["subquery_task"]["query"] for task in command.goto]
    assert dispatched_queries == ["高质量候选", "低质量候选"]


@pytest.mark.asyncio
async def test_transform_query_for_retry_rebuilds_query_plan_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_transform_query(
        self, query: str, *, reason: str, hint: str | None = None, enabled: bool = True
    ) -> SimpleNamespace:
        _ = self, query, reason, hint, enabled
        return SimpleNamespace(
            query="重试后的平台可用性查询",
            rewritten=True,
            reason="retry",
        )

    async def _fake_normalize_rewrite(
        self, query: str, *, llm_enabled: bool | None = None, alias_limit: int | None = None
    ) -> SimpleNamespace:
        _ = self, llm_enabled, alias_limit
        return SimpleNamespace(
            query=query,
            meta={
                "aliases": ["平台 SLA"],
                "entities": ["核心集群"],
                "time_constraints": ["2024"],
                "metric_constraints": ["可用性"],
                "scope_constraints": ["华东区域"],
                "source": "rule_only",
                "fallback_reason": "",
                "recall_risk": "high",
                "drift_risk": False,
                "constraint_preserved": True,
            },
        )

    async def _fake_plan(
        self,
        *,
        normalized_query: str,
        normalized_meta: dict[str, object] | None = None,
    ) -> SimpleNamespace:
        _ = self, normalized_query, normalized_meta
        return SimpleNamespace(
            strategy="paraphrase",
            items=[
                {
                    "kind": "main",
                    "query": "重试后的平台可用性查询",
                    "strategy_source": "canonical",
                    "trigger_reason": "always_keep_main",
                    "semantic_complete": True,
                    "preserve_constraints": True,
                    "retrieval_mode": "hybrid",
                    "priority": 1,
                    "purpose": "primary retrieval",
                },
                {
                    "kind": "paraphrase",
                    "query": "华东区域核心集群平台 SLA 可用性",
                    "strategy_source": "planner_llm",
                    "trigger_reason": "retry_rewrite_paraphrase",
                    "semantic_complete": True,
                    "preserve_constraints": True,
                    "retrieval_mode": "hybrid",
                    "priority": 2,
                    "purpose": "补充约束表达",
                },
            ],
            reasoning="补充时间范围与区域约束后做完整释义",
            fallback_policy={
                "allow_broaden": True,
                "allow_hyde": True,
                "allow_retry_rewrite": True,
            },
            diagnostics={
                "fallback_reason": "none",
                "rejection_counts": {"fragment_rejected": 0},
            },
        )

    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.reflection.QueryRewriteService.transform_query",
        _fake_transform_query,
    )
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.reflection.QueryRewriteService.normalize_rewrite",
        _fake_normalize_rewrite,
    )
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.reflection.KbQueryPlannerService.plan",
        _fake_plan,
    )

    result = await transform_query_for_retry(
        {
            "user_input": "平台可用性是多少",
            "normalized_query": "平台可用性是多少",
            "reflection": {"reason": "insufficient", "hint": "补充时间和范围"},
            "loop_counts": {
                "total_rounds": 0,
                "retrieval_retries": 0,
                "generation_retries": 0,
            },
            "stage_summaries": {},
        },
        runtime=_runtime(),
        settings=_settings(),
    )

    assert result["query_strategy"] == "paraphrase"
    assert result["query_plan_result"]["strategy"] == "paraphrase"
    assert result["query_plan_diagnostics"]["fallback_reason"] == "none"
    assert len(result["query_items"]) >= 2
    assert "message_plan" not in result
    assert "query_bundle" not in result
    assert "prepare_diagnostics" not in result


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

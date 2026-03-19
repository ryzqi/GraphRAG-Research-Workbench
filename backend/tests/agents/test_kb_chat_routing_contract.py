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


def _query_plan_finalize_callable():
    preprocess_module = importlib.import_module("app.agents.kb_chat_agentic.preprocess")
    query_plan_finalize = getattr(preprocess_module, "query_plan_finalize", None)
    assert callable(query_plan_finalize), (
        "query_plan_finalize should exist in app.agents.kb_chat_agentic.preprocess"
    )
    return query_plan_finalize


def _entity_expand_callable():
    preprocess_module = importlib.import_module("app.agents.kb_chat_agentic.preprocess")
    entity_expand = getattr(preprocess_module, "entity_expand", None)
    assert callable(entity_expand), "entity_expand should exist in app.agents.kb_chat_agentic.preprocess"
    return entity_expand


@pytest.mark.asyncio
async def test_query_plan_routes_decomposition_queries_into_scheme_b_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_plan = _query_plan_callable()

    async def _fake_classify_complexity(
        self,
        query: str,
        *,
        recall_risk: str = "unknown",
        has_multi_target: bool = False,
        is_comparison: bool = False,
    ) -> SimpleNamespace:
        _ = self, query, recall_risk, has_multi_target, is_comparison
        return SimpleNamespace(
            strategy="decomposition",
            success=True,
            reasoning="涉及多步骤排障",
            confidence=0.93,
            decision_version="kb_chat_complexity_classify_v5",
            risk_flags=["multi_step"],
        )

    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess.QueryRewriteService.classify_complexity",
        _fake_classify_complexity,
    )

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

    assert command.goto == "decomposition"
    assert command.update["query_strategy"] == "decomposition"
    assert command.update["stage_summaries"]["query_plan"]["next_node"] == "decomposition"
    assert "routing_decisions" not in command.update
    assert "preprocess_next" not in command.update


def test_query_plan_node_label_is_query_focused() -> None:
    assert KB_CHAT_NODE_METADATA["query_plan"]["label"] == "查询规划"
    assert KB_CHAT_NODE_METADATA["query_plan_finalize"]["label"] == "查询定稿"
    assert "prepare_messages" not in KB_CHAT_NODE_METADATA


@pytest.mark.asyncio
async def test_query_plan_finalize_writes_preprocess_routing_decision() -> None:
    query_plan_finalize = _query_plan_finalize_callable()
    command = await query_plan_finalize(
        {
            "user_input": "解释agent的记忆系统",
            "normalized_query": "解释agent的记忆系统",
            "normalized_meta": {
                "recall_risk": "high",
                "drift_risk": False,
                "constraint_preserved": True,
            },
            "query_strategy": "direct",
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
    assert command.goto == "preprocess_exit"
    assert command.update["routing_decisions"]["preprocess"]["next_node"] == "retrieval_subgraph"
    assert (
        command.update["routing_decisions"]["preprocess"]["decision_source"]
        == "query_plan_finalize"
    )
    assert command.update["query_plan_result"]["strategy"] == "direct"
    assert command.update["query_plan_diagnostics"]["fallback_reason"] == "none"
    assert "message_plan" not in command.update
    assert "query_bundle" not in command.update
    assert "prepare_diagnostics" not in command.update


@pytest.mark.asyncio
async def test_entity_expand_routes_to_hyde_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity_expand = _entity_expand_callable()

    async def _fake_entity_expand(
        self,
        queries: list[str],
        *,
        normalized_query: str | None = None,
        aliases: list[str] | None = None,
        entities: list[str] | None = None,
        enabled: bool | None = None,
        max_candidates: int = 8,
        max_variants: int = 6,
        min_confidence: float = 0.55,
    ) -> SimpleNamespace:
        _ = (
            self,
            normalized_query,
            aliases,
            entities,
            enabled,
            max_candidates,
            max_variants,
            min_confidence,
        )
        return SimpleNamespace(
            queries=queries,
            success=True,
            reason="ok",
            diagnostics={"fallback_reason": "", "pruned_count": 0, "pruned_drift": 0},
        )

    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess.QueryRewriteService.entity_expand",
        _fake_entity_expand,
    )

    command = await entity_expand(
        {
            "user_input": "解释 agent memory",
            "normalized_query": "解释 agent memory",
            "normalized_meta": {"aliases": ["智能体记忆"], "entities": ["agent memory"]},
            "multi_queries": ["解释 agent memory"],
            "stage_summaries": {},
        },
        runtime=_runtime(),
        settings=_settings(kb_chat_hyde_enabled=True),
    )

    assert command.goto == "hyde"
    assert command.update["stage_summaries"]["entity_expand"]["next_node"] == "hyde"
    assert command.update["stage_summaries"]["entity_expand"]["hyde_enabled"] is True


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
async def test_dispatch_subqueries_keeps_variant_items_for_decomposition_strategy() -> None:
    command = await dispatch_subqueries(
        {
            "query_strategy": "decomposition",
            "query_items": [
                {
                    "kind": "subquery",
                    "query": "主链路怎么走",
                    "index": 0,
                    "quality_score": 0.92,
                    "use_dense": True,
                    "use_bm25": True,
                },
                {
                    "kind": "variant",
                    "query": "主链路执行顺序",
                    "index": 1,
                    "quality_score": 0.81,
                    "use_dense": True,
                    "use_bm25": True,
                },
            ],
            "stage_summaries": {},
        },
        runtime=_runtime(),
        settings=_settings(
            kb_chat_parallel_retrieval_min_queries=1,
            kb_chat_parallel_retrieval_max_branches=3,
        ),
    )

    dispatched_queries = [task.arg["subquery_task"]["query"] for task in command.goto]
    assert dispatched_queries == ["主链路怎么走", "主链路执行顺序"]


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

    async def _fake_classify_complexity(
        self,
        query: str,
        *,
        recall_risk: str = "unknown",
        has_multi_target: bool = False,
        is_comparison: bool = False,
    ) -> SimpleNamespace:
        _ = self, query, recall_risk, has_multi_target, is_comparison
        return SimpleNamespace(
            strategy="multi_query",
            success=True,
            reasoning="补充时间范围与区域约束后做多路查询",
            confidence=0.91,
            decision_version="kb_chat_complexity_classify_v5",
            risk_flags=["high_recall_risk"],
        )

    async def _fake_generate_variants(self, query: str) -> SimpleNamespace:
        _ = self, query
        return SimpleNamespace(
            queries=["华东区域核心集群平台 SLA 可用性"],
            success=True,
            reason="ok",
        )

    async def _fake_entity_expand(
        self,
        original: list[str],
        *,
        normalized_query: str,
        aliases: list[str],
        entities: list[str],
        enabled: bool,
        max_candidates: int,
        max_variants: int,
        min_confidence: float,
    ) -> SimpleNamespace:
        _ = self, normalized_query, aliases, entities, enabled, max_candidates, max_variants, min_confidence
        return SimpleNamespace(
            queries=original,
            success=True,
            reason="ok",
            diagnostics={"fallback_reason": ""},
        )

    async def _fake_hyde(self, query: str, *, enabled: bool = True) -> SimpleNamespace:
        _ = self, query, enabled
        return SimpleNamespace(queries=[], success=True, reason="disabled")

    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.reflection.QueryRewriteService.transform_query",
        _fake_transform_query,
    )
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.reflection.QueryRewriteService.normalize_rewrite",
        _fake_normalize_rewrite,
    )
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess.QueryRewriteService.classify_complexity",
        _fake_classify_complexity,
    )
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess.QueryRewriteService.generate_variants",
        _fake_generate_variants,
    )
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess.QueryRewriteService.entity_expand",
        _fake_entity_expand,
    )
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess.QueryRewriteService.hyde",
        _fake_hyde,
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

    assert result["query_strategy"] == "multi_query"
    assert result["query_plan_result"]["strategy"] == "multi_query"
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

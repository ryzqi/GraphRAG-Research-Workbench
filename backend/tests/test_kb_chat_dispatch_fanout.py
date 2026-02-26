from __future__ import annotations

import types

import pytest

from app.agents.kb_chat_agentic import reflection


def _settings() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        kb_chat_parallel_retrieval_enabled=True,
        kb_chat_parallel_retrieval_min_queries=2,
        kb_chat_parallel_retrieval_max_branches=4,
        kb_chat_parallel_retrieval_include_main=True,
        retrieval_default_top_k=6,
    )


def test_dispatch_plan_direct_mode_falls_back_to_single_when_only_main() -> None:
    state = {
        "query_strategy": "direct",
        "query_items": [{"kind": "main", "query": "主问题", "priority": 1}],
    }
    goto, diagnostics = reflection._build_subquery_dispatch_plan(state, _settings())
    assert goto == "retrieve"
    assert diagnostics["mode"] == "single_retrieve"
    assert diagnostics["reason"] == "direct_single_query"


def test_dispatch_plan_decomposition_builds_parallel_fanout() -> None:
    state = {
        "query_strategy": "decomposition",
        "query_items": [
            {"kind": "subquery", "query": "子问题1", "priority": 2},
            {"kind": "subquery", "query": "子问题2", "priority": 1},
            {"kind": "main", "query": "主问题", "priority": 3},
        ],
    }
    goto, diagnostics = reflection._build_subquery_dispatch_plan(state, _settings())
    assert isinstance(goto, list)
    assert len(goto) == 3
    assert diagnostics["mode"] == "parallel_fanout"
    assert diagnostics["branch_count"] == 3


def test_dispatch_plan_multi_query_respects_branch_budget() -> None:
    state = {
        "query_strategy": "multi_query",
        "query_items": [
            {"kind": "variant", "query": f"变体{i}", "priority": i}
            for i in range(1, 8)
        ],
        "runtime_config": {"parallel_retrieval_max_branches": 3},
    }
    goto, diagnostics = reflection._build_subquery_dispatch_plan(state, _settings())
    assert isinstance(goto, list)
    assert len(goto) == 3
    assert diagnostics["branch_count"] == 3


@pytest.mark.asyncio
async def test_merge_subquery_context_is_order_stable() -> None:
    settings = _settings()
    base_runs = [
        {
            "subquery_id": "sq_2",
            "index": 1,
            "query": "Q2",
            "kind": "subquery",
            "priority": 2,
            "context": "[S2] 证据2",
            "retrieval_count": 1,
            "success": True,
            "reason": None,
        },
        {
            "subquery_id": "sq_1",
            "index": 0,
            "query": "Q1",
            "kind": "subquery",
            "priority": 1,
            "context": "[S1] 证据1",
            "retrieval_count": 1,
            "success": True,
            "reason": None,
        },
    ]
    result_a = await reflection.merge_subquery_context(
        {"subquery_runs": base_runs},
        settings=settings,
    )
    result_b = await reflection.merge_subquery_context(
        {"subquery_runs": list(reversed(base_runs))},
        settings=settings,
    )
    assert result_a["final_context"] == result_b["final_context"]
    assert result_a["retrieval_plan"]["selected_queries"] == result_b["retrieval_plan"][
        "selected_queries"
    ]


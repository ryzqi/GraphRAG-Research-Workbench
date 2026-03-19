from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.kb_chat_agentic.answer_subgraph import _resolve_subcheck
from app.agents.kb_chat_agentic.reflection import merge_subquery_context
from app.agents.kb_chat_agentic_graph import (
    _current_subquery_runs,
    _resolve_current_subquery_run,
)
from app.agents.kb_chat_trace_display_contract import _resolve_answer_review_run


def _settings(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "app_env": "test",
        "kb_chat_json_safe_policy": "stringify",
        "kb_chat_max_generation_retries": 1,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_merge_subquery_context_ignores_stale_previous_round_runs() -> None:
    state = {
        "loop_counts": {
            "total_rounds": 2,
            "retrieval_retries": 1,
            "generation_retries": 0,
        },
        "memory_keys": {"kb_ids": ["kb-1"]},
        "metrics": {},
        "stage_summaries": {},
        "subquery_runs": [
            {
                "subquery_id": "sq-old",
                "index": 0,
                "query": "old query",
                "retrieval_round": 0,
                "kind": "subquery",
                "priority": 1,
                "context": "[S1] stale evidence",
                "retrieval_count": 1,
                "success": True,
            },
            {
                "subquery_id": "sq-new",
                "index": 0,
                "query": "new query",
                "retrieval_round": 1,
                "kind": "subquery",
                "priority": 1,
                "context": "[S2] fresh evidence",
                "retrieval_count": 1,
                "success": True,
            },
        ],
    }

    result = await merge_subquery_context(
        state,
        settings=_settings(),
        runtime=None,
    )

    assert result["final_context"] == "[S2] fresh evidence"
    assert result["retrieval_plan"]["selected_queries"] == ["new query"]
    assert result["metrics"]["retrieval_layer"]["branch_count"] == 1
    assert result["stage_summaries"]["retrieval_layer"]["retrieval_round"] == 1


def test_graph_subquery_helpers_only_expose_active_round_runs() -> None:
    snapshot = {
        "loop_counts": {"retrieval_retries": 1},
        "subquery_runs": [
            {"subquery_id": "sq-old", "retrieval_round": 0, "query": "old"},
            {"subquery_id": "sq-legacy", "query": "legacy"},
            {"subquery_id": "sq-new", "retrieval_round": 1, "query": "new"},
        ],
    }

    current_runs = _current_subquery_runs(snapshot)

    assert [run["subquery_id"] for run in current_runs] == ["sq-new"]
    assert _resolve_current_subquery_run(snapshot)["query"] == "new"


def test_answer_review_resolvers_ignore_stale_previous_round_runs() -> None:
    state = {
        "loop_counts": {
            "total_rounds": 2,
            "retrieval_retries": 0,
            "generation_retries": 1,
        },
        "answer_review_runs": [
            {
                "check": "citation",
                "review_round": 0,
                "passed": False,
                "reason": "missing_citations",
            },
            {
                "check": "citation",
                "review_round": 1,
                "passed": True,
                "reason": "passed",
            },
        ],
    }

    resolved = _resolve_subcheck(state, "citation")
    trace_resolved = _resolve_answer_review_run(
        {
            **state,
            "answer_review_task": {"check": "citation", "review_round": 1},
        },
        "answer_review_citation",
    )

    assert resolved is not None
    assert resolved["review_round"] == 1
    assert resolved["reason"] == "passed"
    assert trace_resolved["review_round"] == 1
    assert trace_resolved["reason"] == "passed"

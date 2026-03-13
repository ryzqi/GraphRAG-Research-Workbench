from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.kb_chat_agentic.answer_subgraph import (
    _answer_commit,
    _answer_review_dispatch,
    _answer_review_fuse,
)
from app.agents.kb_chat_agentic.reflection import confidence_calibrate
from app.agents.kb_chat_agentic.reflection import dispatch_subqueries
from app.agents.evidence_gate_subgraph import _doc_gate_fuse, _doc_gate_route
from app.agents.kb_chat_trace_nodes import _build_node_output_display_items


def _settings(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "app_env": "test",
        "kb_chat_json_safe_policy": "stringify",
        "kb_chat_parallel_retrieval_min_queries": 2,
        "kb_chat_parallel_retrieval_max_branches": 6,
        "kb_chat_parallel_retrieval_include_main": True,
        "kb_chat_max_generation_retries": 2,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_dispatch_subqueries_does_not_reset_subquery_runs() -> None:
    state = {
        "query_strategy": "direct",
        "query_items": [
            {"kind": "main", "query": "main query", "index": 0},
            {"kind": "hyde", "query": "hyde query", "index": 1},
        ],
        "stage_summaries": {},
        "memory_keys": {"kb_ids": ["kb-1"]},
    }

    command = await dispatch_subqueries(
        state,
        settings=_settings(),
        runtime=None,
    )

    assert "subquery_runs" not in command.update
    assert [task.node for task in command.goto] == [
        "retrieve_subquery",
        "retrieve_subquery",
    ]


@pytest.mark.asyncio
async def test_answer_review_dispatch_does_not_reset_review_runs() -> None:
    state = {
        "loop_counts": {
            "total_rounds": 2,
            "retrieval_retries": 0,
            "generation_retries": 1,
        },
        "stage_summaries": {},
    }

    command = await _answer_review_dispatch(
        state,
        runtime=None,
        settings=_settings(),
    )

    assert "answer_review_runs" not in command.update
    assert [task.arg["answer_review_task"]["review_round"] for task in command.goto] == [
        1,
        1,
        1,
    ]


@pytest.mark.asyncio
async def test_answer_review_fuse_does_not_reset_review_runs() -> None:
    state = {
        "loop_counts": {
            "total_rounds": 2,
            "retrieval_retries": 0,
            "generation_retries": 1,
        },
        "stage_summaries": {},
        "reflection": {},
        "draft_answer": "答案 [S1]",
        "answer_review_runs": [
            {
                "check": "citation",
                "review_round": 0,
                "passed": False,
                "reason": "missing_citations",
                "confidence": 0.1,
                "decision_source": "rule",
            },
            {
                "check": "citation",
                "review_round": 1,
                "passed": True,
                "reason": "passed",
                "confidence": 1.0,
                "decision_source": "rule",
            },
            {
                "check": "factual",
                "review_round": 1,
                "passed": True,
                "reason": "passed",
                "confidence": 0.8,
                "decision_source": "llm",
            },
            {
                "check": "answerability",
                "review_round": 1,
                "passed": True,
                "reason": "passed",
                "confidence": 0.8,
                "decision_source": "llm",
            },
        ],
    }

    command = await _answer_review_fuse(
        state,
        runtime=None,
        settings=_settings(),
    )

    assert "answer_review_runs" not in command.update
    assert command.goto == "cove_check"
    fuse_summary = command.update["stage_summaries"]["answer_review_fuse"]
    assert fuse_summary["review_round"] == 1
    assert fuse_summary["review_breakdown"]["citation"]["review_round"] == 1
    assert fuse_summary["review_breakdown"]["citation"]["reason"] == "passed"


def test_doc_gate_route_uses_stage_summary_instead_of_redundant_state_fields() -> None:
    state = {
        "doc_gate_round": 1,
        "doc_gate_runs": [
            {
                "gate": "sufficiency",
                "round": 1,
                "passed": True,
                "score": 0.8,
                "reason": "passed",
                "extra": {"tokens": 120, "evidence_count": 2},
            },
            {
                "gate": "answerability",
                "round": 1,
                "passed": True,
                "score": 0.7,
                "reason": "passed",
                "extra": {"overlap": 2, "query_terms": 3},
            },
            {
                "gate": "conflict",
                "round": 1,
                "passed": True,
                "score": 1.0,
                "reason": "passed",
                "extra": {"conflict_level": "none", "conflict_pairs": []},
            },
        ],
        "reflection": {},
        "stage_summaries": {},
    }

    fused = _doc_gate_fuse(state)

    assert "doc_gate_scores" not in fused
    assert fused["stage_summaries"]["doc_gate_fuse"]["decision"] == "pass"

    routed = _doc_gate_route(
        {
            **state,
            **fused,
        },
        settings=_settings(kb_chat_max_retrieval_retries=2),
    )

    assert "doc_gate_state" not in routed
    assert routed["reflection"]["relevance_passed"] is True
    assert routed["reflection"]["action"] == "none"
    assert routed["stage_summaries"]["doc_gate_route"]["decision"] == "pass"


@pytest.mark.asyncio
async def test_answer_commit_uses_stage_summary_instead_of_answer_quality() -> None:
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

    assert "answer_quality" not in result
    assert result["reflection"]["action"] == "none"
    assert result["stage_summaries"]["answer_subgraph"]["passed"] is True
    assert result["stage_summaries"]["answer_subgraph"]["next_step"] == "finalize"


def test_confidence_calibrate_uses_doc_gate_route_summary_instead_of_redundant_state() -> None:
    result = confidence_calibrate(
        {
            "doc_gate_state": {
                "confidence": 0.05,
                "reason": "retry",
            },
            "reflection": {
                "review_confidence": 0.8,
            },
            "retrieval_diagnostics": {
                "coverage": 0.6,
                "novelty": 0.5,
                "conflict": 0.1,
            },
            "stage_summaries": {
                "doc_gate_route": {
                    "score": 0.72,
                    "reason": "passed",
                }
            },
        }
    )

    summary = result["stage_summaries"]["confidence_calibrate"]
    assert summary["gate_confidence"] == pytest.approx(0.72)
    assert summary["signals"]["gate_signal"] == pytest.approx(0.72)


def test_evidence_gate_trace_reads_stage_summaries_without_redundant_state_fields() -> None:
    items = _build_node_output_display_items(
        node_name="evidence_gate_subgraph",
        output_snapshot={
            "reflection": {"action": "none"},
            "stage_summaries": {
                "doc_gate_fuse": {
                    "decision": "pass",
                    "score": 0.83,
                    "missing_gates": [],
                },
                "doc_gate_route": {
                    "reason": "passed",
                },
            },
        },
    )

    by_key = {item["key"]: item["value"] for item in items}
    assert by_key["decision"] == "pass"
    assert by_key["score"] == "0.83"
    assert by_key["reason"] == "passed"
    assert "action" not in by_key

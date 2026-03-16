from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain.messages import AIMessage

from app.agents.kb_chat_agentic.answer_subgraph import (
    _answer_commit,
    _answer_review_dispatch,
    _answer_review_fuse,
)
from app.agents.kb_chat_agentic.reflection import confidence_calibrate
from app.agents.kb_chat_agentic.reflection import dispatch_subqueries
from app.agents.evidence_gate_subgraph import _doc_gate_fuse, _doc_gate_route
from app.agents.kb_chat_trace_nodes import (
    _build_node_input_display_items,
    _build_node_output_display_items,
)


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


def test_doc_gate_route_derives_decision_from_doc_gate_runs_without_stage_summary_source() -> None:
    routed = _doc_gate_route(
        {
            "doc_gate_round": 1,
            "doc_gate_runs": [
                {
                    "gate": "sufficiency",
                    "round": 1,
                    "passed": True,
                    "score": 0.9,
                    "reason": "passed",
                    "extra": {"tokens": 120, "evidence_count": 2},
                },
                {
                    "gate": "answerability",
                    "round": 1,
                    "passed": True,
                    "score": 0.8,
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
        },
        settings=_settings(kb_chat_max_retrieval_retries=2),
    )

    assert routed["routing_decisions"]["doc_gate"]["next_node"] == "answer_subgraph"
    assert routed["routing_decisions"]["doc_gate"]["reason"] == "passed"
    assert routed["reflection"]["relevance_passed"] is True


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
    assert result["stage_summaries"]["answer_subgraph"]["next_step"] == "confidence_calibrate"
    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == "最终答案 [S1]"


def test_confidence_calibrate_uses_doc_gate_routing_record_instead_of_stage_summary() -> None:
    result = confidence_calibrate(
        {
            "routing_decisions": {
                "doc_gate": {
                    "next_node": "answer_subgraph",
                    "reason": "passed",
                    "score": 0.72,
                }
            },
            "reflection": {
                "review_confidence": 0.8,
            },
            "retrieval_diagnostics": {
                "coverage": 0.6,
                "novelty": 0.5,
                "conflict": 0.1,
            },
            "stage_summaries": {},
        }
    )

    summary = result["stage_summaries"]["confidence_calibrate"]
    assert summary["gate_confidence"] == pytest.approx(0.72)
    assert summary["signals"]["gate_signal"] == pytest.approx(0.72)


TRACE_EVIDENCE_CONTEXT = "[S1] CoT 关注线性推理。\n\n[S2] ToT 允许树状探索。"
TRACE_EVIDENCE_LINES = [
    "文档名：未命名文档\nChunk 内容：CoT 关注线性推理。",
    "文档名：未命名文档\nChunk 内容：ToT 允许树状探索。",
]

TRACE_INPUT_KEYS_BY_NODE = {
    "preprocess_subgraph": ["user_input"],
    "merge_context": ["user_input", "recent_turns"],
    "coref_rewrite": ["user_input"],
    "ambiguity_check": ["normalized_query"],
    "normalize_rewrite": ["normalized_query"],
    "complexity_classify": ["user_input"],
    "generate_variants_mod": ["normalized_query"],
    "decomposition": ["normalized_query"],
    "generate_variants": ["normalized_query"],
    "entity_expand": ["normalized_query"],
    "hyde": ["normalized_query"],
    "prepare_messages": ["normalized_query", "sub_queries", "multi_queries"],
    "preprocess_exit": ["normalized_query"],
    "retrieval_subgraph": ["query_items"],
    "retrieval_budget_plan": ["normalized_query", "query_items"],
    "dispatch_subqueries": ["query_items"],
    "retrieve_subquery": ["subquery"],
    "merge_subquery_context": ["retrieved_evidence"],
    "retrieve": ["query_items"],
    "context_compress": ["retrieved_evidence"],
    "evidence_gate_subgraph": ["normalized_query", "current_evidence"],
    "doc_gate_dispatch": ["normalized_query", "current_evidence"],
    "doc_gate_sufficiency": ["current_evidence"],
    "doc_gate_answerability": ["current_evidence"],
    "doc_gate_conflict": ["current_evidence"],
    "doc_gate_fuse": ["gate_results"],
    "doc_gate_route": ["normalized_query", "gate_results"],
    "transform_query": ["normalized_query"],
    "answer_subgraph": ["normalized_query", "current_evidence"],
    "draft_generate": ["normalized_query", "current_evidence"],
    "answer_review_dispatch": ["draft_answer"],
    "answer_review_citation": ["draft_answer"],
    "answer_review_factual": ["draft_answer"],
    "answer_review_answerability": ["draft_answer"],
    "answer_review_fuse": ["review_results"],
    "cove_check": ["draft_answer"],
    "chain_of_verification": ["draft_answer"],
    "claim_citation_check": ["draft_answer"],
    "answer_repair": ["draft_answer"],
    "answer_commit": ["candidate_answer"],
    "force_exit": ["exit_action", "candidate_answer"],
    "confidence_calibrate": ["final_answer"],
}

TRACE_OUTPUT_KEYS_BY_NODE = {
    "preprocess_subgraph": ["decision", "reason", "next_node_label"],
    "merge_context": ["merged_context"],
    "coref_rewrite": ["normalized_query"],
    "ambiguity_check": ["decision", "reason", "clarification_prompt"],
    "normalize_rewrite": ["normalized_query"],
    "complexity_classify": ["decision", "reason", "next_node_label"],
    "generate_variants_mod": ["multi_queries"],
    "decomposition": ["sub_queries"],
    "generate_variants": ["multi_queries"],
    "entity_expand": ["multi_queries"],
    "hyde": ["hyde_docs"],
    "prepare_messages": ["query_items"],
    "preprocess_exit": ["decision", "reason", "next_node_label", "final_answer"],
    "retrieval_subgraph": ["decision", "reason", "next_node_label"],
    "retrieval_budget_plan": ["planned_query_count", "planned_per_query_top_k"],
    "dispatch_subqueries": ["dispatch_targets"],
    "retrieve_subquery": ["retrieved_evidence"],
    "merge_subquery_context": ["retrieved_evidence"],
    "retrieve": ["retrieved_evidence"],
    "context_compress": ["compressed_evidence"],
    "evidence_gate_subgraph": ["decision", "reason", "next_node_label"],
    "doc_gate_dispatch": ["dispatch_targets"],
    "doc_gate_sufficiency": ["decision", "reason", "next_node_label"],
    "doc_gate_answerability": ["decision", "reason", "next_node_label"],
    "doc_gate_conflict": ["decision", "reason", "next_node_label"],
    "doc_gate_fuse": ["decision", "reason", "next_node_label"],
    "doc_gate_route": ["decision", "reason", "next_node_label"],
    "transform_query": ["normalized_query"],
    "answer_subgraph": ["decision", "reason", "next_node_label"],
    "draft_generate": ["draft_answer"],
    "answer_review_dispatch": ["review_checks"],
    "answer_review_citation": ["decision", "reason", "next_node_label"],
    "answer_review_factual": ["decision", "reason", "next_node_label"],
    "answer_review_answerability": ["decision", "reason", "next_node_label"],
    "answer_review_fuse": ["decision", "reason", "next_node_label"],
    "cove_check": ["decision", "reason", "next_node_label"],
    "chain_of_verification": ["decision", "reason", "next_node_label"],
    "claim_citation_check": ["decision", "reason", "next_node_label"],
    "answer_repair": ["repaired_answer"],
    "answer_commit": ["final_answer"],
    "force_exit": ["final_answer", "reason", "next_node_label"],
    "confidence_calibrate": ["decision", "reason", "next_node_label"],
}


def _trace_base_snapshot() -> dict[str, Any]:
    return {
        "user_input": "解释 CoT 和 ToT 的区别",
        "normalized_query": "解释 CoT 和 ToT 的区别",
        "coref_query": "解释 CoT 和 ToT 的区别",
        "query_items": [
            {"kind": "main", "query": "CoT 与 ToT 区别"},
            {"kind": "comparison", "query": "Tree of Thoughts 与 Chain of Thought"},
        ],
        "sub_queries": ["CoT 是什么", "ToT 是什么"],
        "multi_queries": ["CoT 与 ToT 区别", "Tree of Thoughts explanation"],
        "hyde_docs": ["HyDE 全文一", "HyDE 全文二"],
        "draft_answer": "这是草稿答案全文。",
        "final_answer": "这是最终答案全文。",
        "best_answer": "这是候选答案全文。",
        "final_context": TRACE_EVIDENCE_CONTEXT,
        "context_frame": {
            "recent_turns": [
                {"role": "user", "text": "前一轮问题"},
                {"role": "assistant", "text": "前一轮回答"},
            ]
        },
        "query_strategy": "decomposition",
        "query_strategy_confidence": 0.91,
        "doc_gate_round": 1,
        "doc_gate_task": {"gate": "sufficiency", "round": 1},
        "doc_gate_runs": [
            {
                "gate": "sufficiency",
                "round": 1,
                "passed": True,
                "score": 0.92,
                "reason": "evidence_covers_question",
                "extra": {"tokens": 128, "evidence_count": 2},
            },
            {
                "gate": "answerability",
                "round": 1,
                "passed": True,
                "score": 0.88,
                "reason": "question_can_be_answered",
                "extra": {"overlap": 4, "query_terms": 5},
            },
            {
                "gate": "conflict",
                "round": 1,
                "passed": True,
                "score": 0.96,
                "reason": "no_conflict_detected",
                "extra": {"conflict_markers": 0},
            },
        ],
        "answer_review_task": {"check": "citation", "review_round": 1},
        "answer_review_runs": [
            {
                "check": "citation",
                "review_round": 1,
                "passed": True,
                "reason": "关键断言均有引用",
                "confidence": 0.95,
                "decision_source": "rule",
            },
            {
                "check": "factual",
                "review_round": 1,
                "passed": False,
                "reason": "第二段与证据不一致",
                "confidence": 0.41,
                "decision_source": "llm",
            },
            {
                "check": "answerability",
                "review_round": 1,
                "passed": True,
                "reason": "已直接回答用户问题",
                "confidence": 0.88,
                "decision_source": "llm",
            },
        ],
        "subquery_task": {
            "subquery_id": "sq-1",
            "index": 0,
            "kind": "main",
            "query": "CoT 与 ToT 区别",
        },
        "subquery_runs": [
            {
                "subquery_id": "sq-1",
                "index": 0,
                "kind": "main",
                "query": "CoT 与 ToT 区别",
                "context": TRACE_EVIDENCE_CONTEXT,
                "retrieval_count": 2,
                "success": True,
                "reason": None,
            }
        ],
        "loop_counts": {"total_rounds": 1, "retrieval_retries": 0, "generation_retries": 1},
        "reflection": {
            "action": "force_exit",
            "reason": "证据已足够",
            "review_passed": True,
            "review_confidence": 0.91,
        },
        "routing_decisions": {
            "preprocess": {"next_node": "retrieval_subgraph", "reason": "完成预处理"},
            "doc_gate": {"next_node": "answer_subgraph", "reason": "证据足以回答", "score": 0.83},
            "answer_subgraph": {
                "next_node": "confidence_calibrate",
                "reason": "答案审查通过",
            },
        },
        "metrics": {"retrieval_layer": {"evidence_count": 2, "retrieval_count": 2}},
        "compression_stats": {
            "token_limit": 2500,
            "input_tokens": 320,
            "output_tokens": 210,
            "truncated": True,
        },
        "clarification_payload": {"question": "你更关注原理还是应用场景？"},
        "confidence_level": "high",
        "stage_summaries": {
            "complexity_classify": {
                "strategy": "decomposition",
                "reasoning": "涉及方法比较与边界说明",
                "goto": "decomposition",
            },
            "retrieval_budget_plan": {"query_count": 2, "per_query_top_k": 6},
            "doc_gate_fuse": {"decision": "pass", "reason": "三项门控均通过"},
            "doc_gate_route": {"decision": "pass", "reason": "证据足以回答"},
            "answer_review_dispatch": {
                "checks": ["citation", "factual", "answerability"]
            },
            "answer_review_fuse": {"decision": "retry", "reason": "事实审查未通过"},
            "confidence_calibrate": {
                "confidence_level": "high",
                "reason": "多信号一致",
            },
        },
    }


def _trace_snapshot_for_node(node_name: str) -> dict[str, Any]:
    snapshot = _trace_base_snapshot()
    trace_goto = {
        "preprocess_subgraph": "retrieval_subgraph",
        "complexity_classify": "decomposition",
        "preprocess_exit": "force_exit",
        "retrieval_subgraph": "evidence_gate_subgraph",
        "evidence_gate_subgraph": "answer_subgraph",
        "doc_gate_sufficiency": "doc_gate_fuse",
        "doc_gate_answerability": "doc_gate_fuse",
        "doc_gate_conflict": "doc_gate_fuse",
        "doc_gate_fuse": "doc_gate_route",
        "doc_gate_route": "answer_subgraph",
        "answer_subgraph": "confidence_calibrate",
        "answer_review_citation": "answer_review_fuse",
        "answer_review_factual": "answer_review_fuse",
        "answer_review_answerability": "answer_review_fuse",
        "answer_review_fuse": "cove_check",
        "cove_check": "chain_of_verification",
        "chain_of_verification": "claim_citation_check",
        "claim_citation_check": "answer_repair",
        "answer_repair": "answer_commit",
    }
    trace_targets = {
        "dispatch_subqueries": ["retrieve_subquery"],
        "doc_gate_dispatch": [
            "doc_gate_sufficiency",
            "doc_gate_answerability",
            "doc_gate_conflict",
        ],
        "answer_review_dispatch": [
            "answer_review_citation",
            "answer_review_factual",
            "answer_review_answerability",
        ],
    }
    if node_name in trace_goto:
        snapshot["__trace_command__"] = {"goto": trace_goto[node_name]}
    if node_name in trace_targets:
        snapshot["__trace_command__"] = {"goto_targets": trace_targets[node_name]}
    if node_name == "ambiguity_check":
        snapshot["stage_summaries"]["ambiguity_check"] = {
            "ambiguous": True,
            "reason": "缺少时间范围",
        }
        snapshot["final_answer"] = "你更关注原理还是应用场景？"
    if node_name == "normalize_rewrite":
        snapshot["stage_summaries"]["normalize_rewrite"] = {"rewritten": True}
    if node_name == "coref_rewrite":
        snapshot["normalized_query"] = "北京市 2025 年社保缴费基数"
    if node_name == "preprocess_exit":
        snapshot["routing_decisions"]["preprocess"] = {
            "next_node": "force_exit",
            "reason": "已能直接回答",
        }
        snapshot["final_answer"] = "请先确认你想比较原理还是落地场景。"
    if node_name == "force_exit":
        snapshot["final_answer"] = "根据现有资料，先给出可确认结论。"
    if node_name == "answer_repair":
        snapshot["final_answer"] = "这是修复后的答案全文。"
    if node_name == "answer_commit":
        snapshot["final_answer"] = "这是最终提交答案全文。"
    if node_name == "confidence_calibrate":
        snapshot["final_answer"] = "这是最终答案全文。"
    return snapshot


@pytest.mark.parametrize(
    ("node_name", "expected_keys"),
    list(TRACE_INPUT_KEYS_BY_NODE.items()),
)
def test_trace_display_input_contract_matches_spec(
    node_name: str, expected_keys: list[str]
) -> None:
    items = _build_node_input_display_items(
        node_name=node_name,
        input_snapshot=_trace_snapshot_for_node(node_name),
    )

    assert [item["key"] for item in items] == expected_keys


@pytest.mark.parametrize(
    ("node_name", "expected_keys"),
    list(TRACE_OUTPUT_KEYS_BY_NODE.items()),
)
def test_trace_display_output_contract_matches_spec(
    node_name: str, expected_keys: list[str]
) -> None:
    items = _build_node_output_display_items(
        node_name=node_name,
        output_snapshot=_trace_snapshot_for_node(node_name),
    )

    assert [item["key"] for item in items] == expected_keys


def test_complexity_classify_output_is_curated_and_businessized() -> None:
    items = _build_node_output_display_items(
        node_name="complexity_classify",
        output_snapshot=_trace_snapshot_for_node("complexity_classify"),
    )

    by_key = {item["key"]: item["value"] for item in items}
    assert by_key == {
        "decision": "复杂问题",
        "reason": "涉及方法比较与边界说明",
        "next_node_label": "问题分解",
    }


def test_retrieval_outputs_and_current_evidence_inputs_share_same_evidence_format() -> None:
    retrieve_items = _build_node_output_display_items(
        node_name="retrieve",
        output_snapshot=_trace_snapshot_for_node("retrieve"),
    )
    gate_input_items = _build_node_input_display_items(
        node_name="evidence_gate_subgraph",
        input_snapshot=_trace_snapshot_for_node("evidence_gate_subgraph"),
    )

    retrieve_by_key = {item["key"]: item["value"] for item in retrieve_items}
    gate_by_key = {item["key"]: item["value"] for item in gate_input_items}
    assert retrieve_by_key["retrieved_evidence"] == TRACE_EVIDENCE_LINES
    assert gate_by_key["current_evidence"] == TRACE_EVIDENCE_LINES


def test_dispatch_and_review_lists_are_businessized_string_arrays() -> None:
    dispatch_items = _build_node_output_display_items(
        node_name="doc_gate_dispatch",
        output_snapshot=_trace_snapshot_for_node("doc_gate_dispatch"),
    )
    review_dispatch_items = _build_node_output_display_items(
        node_name="answer_review_dispatch",
        output_snapshot=_trace_snapshot_for_node("answer_review_dispatch"),
    )
    gate_fuse_input = _build_node_input_display_items(
        node_name="doc_gate_fuse",
        input_snapshot=_trace_snapshot_for_node("doc_gate_fuse"),
    )
    review_fuse_input = _build_node_input_display_items(
        node_name="answer_review_fuse",
        input_snapshot=_trace_snapshot_for_node("answer_review_fuse"),
    )

    dispatch_by_key = {item["key"]: item["value"] for item in dispatch_items}
    review_dispatch_by_key = {
        item["key"]: item["value"] for item in review_dispatch_items
    }
    gate_fuse_by_key = {item["key"]: item["value"] for item in gate_fuse_input}
    review_fuse_by_key = {item["key"]: item["value"] for item in review_fuse_input}

    assert dispatch_by_key["dispatch_targets"] == [
        "证据充分度",
        "可回答性",
        "证据冲突检测",
    ]
    assert review_dispatch_by_key["review_checks"] == [
        "引用覆盖审查",
        "事实正确性审查",
        "可回答性审查",
    ]
    assert gate_fuse_by_key["gate_results"] == [
        "证据充分度：通过｜原因：evidence_covers_question",
        "可回答性：通过｜原因：question_can_be_answered",
        "证据冲突检测：通过｜原因：no_conflict_detected",
    ]
    assert review_fuse_by_key["review_results"] == [
        "引用覆盖审查：通过｜原因：关键断言均有引用",
        "事实正确性审查：未通过｜原因：第二段与证据不一致",
        "可回答性审查：通过｜原因：已直接回答用户问题",
    ]


def test_error_phase_display_preserves_inputs_and_user_readable_error() -> None:
    input_items = _build_node_input_display_items(
        node_name="retrieve",
        input_snapshot=_trace_snapshot_for_node("retrieve"),
    )
    output_items = _build_node_output_display_items(
        node_name="retrieve",
        output_snapshot=_trace_snapshot_for_node("retrieve"),
        error_summary="节点执行失败",
    )

    assert [item["key"] for item in input_items] == ["query_items"]
    assert output_items[-1] == {
        "key": "error_summary",
        "label": "错误信息",
        "value": "节点执行失败",
    }

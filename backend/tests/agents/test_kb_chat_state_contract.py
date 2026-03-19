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
from app.agents.kb_chat_agentic.reflection import dispatch_subqueries
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
    assert command.goto == "answer_commit"
    fuse_summary = command.update["stage_summaries"]["answer_review_fuse"]
    assert fuse_summary["review_round"] == 1
    assert fuse_summary["review_breakdown"]["citation"]["review_round"] == 1
    assert fuse_summary["review_breakdown"]["citation"]["reason"] == "passed"


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
    assert result["stage_summaries"]["answer_subgraph"]["next_step"] == "END"
    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == "最终答案 [S1]"


TRACE_EVIDENCE_CONTEXT = "[S1] CoT 关注线性推理。\n\n[S2] ToT 允许树状探索。"
TRACE_EVIDENCE_LINES = [
    "文档名：未命名文档\nChunk 内容：CoT 关注线性推理。",
    "文档名：未命名文档\nChunk 内容：ToT 允许树状探索。",
]

TRACE_INPUT_KEYS_BY_NODE = {
    "preprocess_subgraph": ["user_input"],
    "merge_context": ["user_input", "recent_turns"],
    "resolve_reference": ["user_input"],
    "ambiguity_check": ["resolved_query"],
    "query_normalize": ["resolved_query"],
    "query_plan": ["normalized_query"],
    "preprocess_exit": ["normalized_query"],
    "retrieval_subgraph": ["query_items"],
    "retrieval_plan": ["normalized_query", "query_items"],
    "dispatch_subqueries": ["query_items"],
    "retrieve_subquery": ["subquery"],
    "merge_subquery_context": ["retrieved_evidence"],
    "retrieve": ["query_items"],
    "context_compress": ["retrieved_evidence"],
    "transform_query": ["normalized_query"],
    "answer_subgraph": ["normalized_query", "current_evidence"],
    "draft_generate": ["normalized_query", "current_evidence"],
    "answer_review_dispatch": ["draft_answer"],
    "answer_review_citation": ["draft_answer"],
    "answer_review_factual": ["draft_answer"],
    "answer_review_answerability": ["draft_answer"],
    "answer_review_fuse": ["review_results"],
    "answer_repair": ["draft_answer"],
    "answer_commit": ["candidate_answer"],
    "force_exit": ["exit_action", "candidate_answer"],
}

TRACE_OUTPUT_KEYS_BY_NODE = {
    "preprocess_subgraph": ["decision", "reason", "next_node_label"],
    "merge_context": ["merged_context"],
    "resolve_reference": ["resolved_query"],
    "ambiguity_check": ["decision", "reason", "clarification_prompt"],
    "query_normalize": ["normalized_query"],
    "query_plan": ["query_items"],
    "preprocess_exit": ["decision", "reason", "next_node_label", "final_answer"],
    "retrieval_subgraph": ["decision", "reason", "next_node_label"],
    "retrieval_plan": ["planned_query_count", "planned_per_query_top_k"],
    "dispatch_subqueries": ["dispatch_targets"],
    "retrieve_subquery": ["retrieved_evidence"],
    "merge_subquery_context": ["merged_evidence"],
    "retrieve": ["retrieved_evidence"],
    "context_compress": ["compressed_evidence"],
    "transform_query": ["normalized_query"],
    "answer_subgraph": ["decision", "reason", "next_node_label"],
    "draft_generate": ["draft_answer"],
    "answer_review_dispatch": ["review_checks"],
    "answer_review_citation": ["decision", "reason", "next_node_label"],
    "answer_review_factual": ["decision", "reason", "next_node_label"],
    "answer_review_answerability": ["decision", "reason", "next_node_label"],
    "answer_review_fuse": ["decision", "reason", "next_node_label"],
    "answer_repair": ["repaired_answer"],
    "answer_commit": ["final_answer"],
    "force_exit": [],
}


def _trace_base_snapshot() -> dict[str, Any]:
    return {
        "user_input": "解释 CoT 和 ToT 的区别",
        "normalized_query": "解释 CoT 和 ToT 的区别",
        "resolved_query": "解释 CoT 和 ToT 的区别",
        "query_items": [
            {
                "kind": "main",
                "query": "CoT 与 ToT 区别",
                "strategy_source": "canonical",
                "trigger_reason": "always_keep_main",
            },
            {
                "kind": "paraphrase",
                "query": "Tree of Thoughts 与 Chain of Thought 的区别",
                "strategy_source": "planner_llm",
                "trigger_reason": "comparison_paraphrase",
            },
        ],
        "query_plan_result": {
            "strategy": "decomposition",
            "reasoning": "涉及方法比较与边界说明",
            "fallback_policy": {
                "allow_broaden": True,
                "allow_hyde": True,
                "allow_retry_rewrite": True,
            },
        },
        "query_plan_diagnostics": {
            "selected_count": 2,
            "rejection_counts": {"fragment_rejected": 1},
        },
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
            "action": "none",
            "reason": "答案审查通过",
            "review_passed": True,
            "review_confidence": 0.91,
        },
        "routing_decisions": {
            "preprocess": {"next_node": "retrieval_subgraph", "reason": "完成预处理"},
            "answer_subgraph": {
                "next_node": "END",
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
        "stage_summaries": {
            "query_plan": {
                "strategy": "decomposition",
                "reasoning": "涉及方法比较与边界说明",
                "selected_count": 2,
            },
            "retrieval_plan": {"query_count": 2, "per_query_top_k": 6},
            "answer_review_dispatch": {
                "checks": ["citation", "factual", "answerability"]
            },
            "answer_review_fuse": {"decision": "retry", "reason": "事实审查未通过"},
        },
    }


def _trace_snapshot_for_node(node_name: str) -> dict[str, Any]:
    snapshot = _trace_base_snapshot()
    trace_goto = {
        "preprocess_subgraph": "retrieval_subgraph",
        "query_plan": "preprocess_exit",
        "preprocess_exit": "force_exit",
        "retrieval_subgraph": "answer_subgraph",
        "answer_subgraph": "END",
        "answer_review_citation": "answer_review_fuse",
        "answer_review_factual": "answer_review_fuse",
        "answer_review_answerability": "answer_review_fuse",
        "answer_review_fuse": "answer_repair",
        "answer_repair": "answer_commit",
    }
    trace_targets = {
        "dispatch_subqueries": ["retrieve_subquery"],
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
    if node_name == "query_normalize":
        snapshot["stage_summaries"]["query_normalize"] = {"rewritten": True}
    if node_name == "resolve_reference":
        snapshot["resolved_query"] = "北京市 2025 年社保缴费基数"
    if node_name == "merge_context":
        snapshot["context_frame"]["summary_text"] = "对话聚焦 CoT 与 ToT 的推理路径差异"
        snapshot["merged_context"] = (
            "对话摘要：\n对话聚焦 CoT 与 ToT 的推理路径差异\n\n"
            "用户问题：解释 CoT 和 ToT 的区别"
        )
    if node_name == "preprocess_exit":
        snapshot["routing_decisions"]["preprocess"] = {
            "next_node": "force_exit",
            "reason": "已能直接回答",
        }
        snapshot["final_answer"] = "请先确认你想比较原理还是落地场景。"
    if node_name == "transform_query":
        snapshot["normalized_query"] = "CoT ToT 区别 线性推理 树状搜索"
        snapshot["resolved_query"] = "解释 CoT 和 ToT 的区别"
        snapshot["stage_summaries"]["transform_query"] = {"rewritten": True}
    if node_name == "force_exit":
        snapshot["final_answer"] = "根据现有资料，先给出可确认结论。"
    if node_name == "answer_repair":
        snapshot["final_answer"] = "这是修复后的答案全文。"
    if node_name == "answer_commit":
        snapshot["final_answer"] = "这是最终提交答案全文。"
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


def test_query_plan_output_is_query_focused_and_metadata_aware() -> None:
    items = _build_node_output_display_items(
        node_name="query_plan",
        output_snapshot=_trace_snapshot_for_node("query_plan"),
    )

    assert items == [
        {
            "key": "query_items",
            "label": "检索查询项",
            "value": [
                "1. [main] CoT 与 ToT 区别",
                "2. [paraphrase] Tree of Thoughts 与 Chain of Thought 的区别",
            ],
        }
    ]


def test_merge_context_omits_output_when_only_repeating_user_input_and_recent_turns() -> None:
    snapshot = {
        "user_input": "什么是 CoT",
        "merged_context": "最近对话：\n助手: CoT 是逐步推理。\n\n用户问题：什么是 CoT",
        "context_frame": {
            "recent_turns": [{"role": "assistant", "text": "CoT 是逐步推理。"}],
            "summary_text": "",
            "memory_snippet": "",
        },
    }

    items = _build_node_output_display_items(
        node_name="merge_context",
        output_snapshot=snapshot,
    )

    assert items == []


def test_merge_subquery_context_uses_merged_evidence_label() -> None:
    items = _build_node_output_display_items(
        node_name="merge_subquery_context",
        output_snapshot=_trace_snapshot_for_node("merge_subquery_context"),
    )

    assert items == [
        {
            "key": "merged_evidence",
            "label": "合并后证据",
            "value": TRACE_EVIDENCE_LINES,
        }
    ]


def test_transform_query_omits_output_when_retry_rewrite_is_unchanged() -> None:
    snapshot = _trace_base_snapshot()
    snapshot["stage_summaries"]["transform_query"] = {"rewritten": False}

    items = _build_node_output_display_items(
        node_name="transform_query",
        output_snapshot=snapshot,
    )

    assert items == []


def test_force_exit_removes_output_items_from_display_contract() -> None:
    items = _build_node_output_display_items(
        node_name="force_exit",
        output_snapshot=_trace_snapshot_for_node("force_exit"),
    )

    assert items == []


def test_retrieval_outputs_and_current_evidence_inputs_share_same_evidence_format() -> None:
    retrieve_items = _build_node_output_display_items(
        node_name="retrieve",
        output_snapshot=_trace_snapshot_for_node("retrieve"),
    )
    answer_input_items = _build_node_input_display_items(
        node_name="answer_subgraph",
        input_snapshot=_trace_snapshot_for_node("answer_subgraph"),
    )

    retrieve_by_key = {item["key"]: item["value"] for item in retrieve_items}
    answer_by_key = {item["key"]: item["value"] for item in answer_input_items}
    assert retrieve_by_key["retrieved_evidence"] == TRACE_EVIDENCE_LINES
    assert answer_by_key["current_evidence"] == TRACE_EVIDENCE_LINES


def test_review_lists_are_businessized_string_arrays() -> None:
    review_dispatch_items = _build_node_output_display_items(
        node_name="answer_review_dispatch",
        output_snapshot=_trace_snapshot_for_node("answer_review_dispatch"),
    )
    review_fuse_input = _build_node_input_display_items(
        node_name="answer_review_fuse",
        input_snapshot=_trace_snapshot_for_node("answer_review_fuse"),
    )

    review_dispatch_by_key = {
        item["key"]: item["value"] for item in review_dispatch_items
    }
    review_fuse_by_key = {item["key"]: item["value"] for item in review_fuse_input}

    assert review_dispatch_by_key["review_checks"] == [
        "引用覆盖审查",
        "事实正确性审查",
        "可回答性审查",
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


def test_ambiguity_check_prefers_model_reason_over_technical_reason() -> None:
    snapshot = _trace_snapshot_for_node("ambiguity_check")
    snapshot["stage_summaries"]["ambiguity_check"] = {
        "ambiguous": True,
        "reason": "error",
        "reason_code": "missing_time",
        "model_reason": "缺少时间范围，继续检索会让答案口径不稳定。",
    }

    items = _build_node_output_display_items(
        node_name="ambiguity_check",
        output_snapshot=snapshot,
    )

    assert items == [
        {"key": "decision", "label": "结论", "value": "需要澄清"},
        {
            "key": "reason",
            "label": "原因",
            "value": "缺少时间范围，继续检索会让答案口径不稳定。",
        },
        {
            "key": "clarification_prompt",
            "label": "澄清提示",
            "value": "你更关注原理还是应用场景？",
        },
    ]


def test_ambiguity_check_falls_back_to_reason_code_when_model_reason_missing() -> None:
    snapshot = _trace_snapshot_for_node("ambiguity_check")
    snapshot["stage_summaries"]["ambiguity_check"] = {
        "ambiguous": True,
        "reason": "invalid_schema",
        "reason_code": "missing_time",
        "model_reason": "",
    }

    items = _build_node_output_display_items(
        node_name="ambiguity_check",
        output_snapshot=snapshot,
    )

    assert items == [
        {"key": "decision", "label": "结论", "value": "需要澄清"},
        {"key": "reason", "label": "原因", "value": "缺少时间范围"},
        {
            "key": "clarification_prompt",
            "label": "澄清提示",
            "value": "你更关注原理还是应用场景？",
        },
    ]

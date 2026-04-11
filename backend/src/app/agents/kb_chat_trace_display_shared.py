"""KB Chat trace 节点展示契约辅助函数。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import re
from typing import Any

DisplayItem = dict[str, Any]
NodeLabelResolver = Callable[[str | None], str | None]

_EVIDENCE_BLOCK_RE = re.compile(
    r"^\[([^\[\]\n]{1,128})\]\s*(.*?)(?=^\[[^\[\]\n]{1,128}\]\s|\Z)",
    re.MULTILINE | re.DOTALL,
)

_NODE_SUMMARY_KEY_MAP: dict[str, str] = {
    "retrieve": "retrieval_layer",
    "draft_generate": "generator",
    "answer_commit": "answer_subgraph",
    "answer_review_citation": "answer_review",
    "answer_review": "answer_review",
}

_ANSWER_REVIEW_NODE_TO_CHECK: dict[str, str] = {
    "answer_review_citation": "citation",
    "answer_review": "answer",
}

_DOC_GATE_NODE_TO_GATE: dict[str, str] = {}
_GATE_LABELS: dict[str, str] = {}

_REVIEW_CHECK_LABELS: dict[str, str] = {
    "citation": "引用覆盖审查",
    "answer": "回答有效性审查",
}

_AMBIGUITY_REASON_CODE_LABELS: dict[str, str] = {
    "missing_entity": "缺少具体对象",
    "missing_scope": "缺少范围约束",
    "missing_time": "缺少时间范围",
    "missing_metric": "缺少指标口径",
    "coref_uncertain": "指代对象不明确",
    "mixed": "关键信息不完整",
}
_AMBIGUITY_TECHNICAL_REASONS: set[str] = {
    "error",
    "invalid_schema",
    "multiple_structured_outputs",
    "empty_structured_response",
    "prompt_missing",
    "prompt_error",
    "ambiguous_query",
    "model_structured",
    "model_failed_guardrail_fallback",
    "guardrail_empty_query",
    "guardrail_fallback",
}
_AMBIGUITY_DEFAULT_REASON_TRUE = "问题缺少关键信息，需先澄清后再检索。"
_AMBIGUITY_DEFAULT_REASON_FALSE = "未命中需澄清信号，可直接继续检索。"
_QUERY_PLAN_REASON_DIRECT = "未命中复杂问题信号，按主问题并辅以 HyDE 补强检索。"
_QUERY_PLAN_REASON_MULTI_QUERY = (
    "目标单一但召回风险较高，先做多路查询扩展，再进入 HyDE 补强。"
)
_QUERY_PLAN_REASON_DECOMPOSITION = (
    "命中比较或多目标信号，先做问题拆解，再进入 HyDE 补强。"
)
_QUERY_PLAN_REASON_DECOMPOSITION_GENERIC = (
    "问题涉及多步骤或多视角信息，先做问题拆解，再进入 HyDE 补强。"
)

_BUSINESS_LABEL_FALLBACKS: dict[str, str] = {
    "__end__": "结束",
    "end": "结束",
    "none": "结束",
    "preprocess_subgraph": "预处理子图",
    "merge_context": "上下文合并",
    "resolve_reference": "指代消解",
    "ambiguity_check": "歧义判断",
    "query_normalize": "问题规范",
    "query_plan": "查询规划",
    "decomposition": "问题拆解",
    "generate_variants": "多路查询扩展",
    "hyde": "假设文档扩展",
    "query_plan_finalize": "查询定稿",
    "preprocess_exit": "预处理出口",
    "retrieval_subgraph": "检索子图",
    "retrieval_plan": "检索预算规划",
    "dispatch_subqueries": "子查询派发",
    "retrieve_subquery": "子查询检索",
    "merge_subquery_context": "子查询上下文合并",
    "retrieve": "知识检索",
    "context_compress": "上下文压缩",
    "transform_query": "查询改写",
    "answer_subgraph": "答案子图",
    "draft_generate": "草稿生成",
    "answer_review_dispatch": "审查分发",
    "answer_review_citation": "引用覆盖审查",
    "answer_review": "回答有效性审查",
    "answer_review_fuse": "审查结果汇总",
    "answer_repair": "答案修复",
    "answer_commit": "答案提交",
    "force_exit": "结束",
    "retry": "继续检索",
    "retry_conflict": "继续检索",
    "transform_query_retry": "继续检索",
    "clarify": "结束",
}

_DISPLAY_LABELS: dict[str, str] = {
    "user_input": "用户问题",
    "recent_turns": "最近对话",
    "merged_context": "合并上下文",
    "resolved_query": "指代消解后问题",
    "normalized_query": "规范化问题",
    "query_items": "检索查询项",
    "draft_answer": "草稿答案",
    "current_evidence": "当前证据",
    "subquery": "分支查询",
    "exit_action": "终止动作",
    "candidate_answer": "候选答案",
    "gate_results": "门控结果",
    "review_results": "审查结果",
    "decision": "结论",
    "reason": "原因",
    "next_node_label": "下一跳",
    "clarification_prompt": "澄清提示",
    "dispatch_targets": "派发目标",
    "sub_queries": "分解问题",
    "multi_queries": "多路查询",
    "review_checks": "审查项",
    "planned_query_count": "计划查询数",
    "planned_per_query_top_k": "每路召回条数",
    "retrieved_evidence": "检索证据",
    "merged_evidence": "合并后证据",
    "compressed_evidence": "压缩后证据",
    "hyde_docs": "HyDE 文档",
    "repaired_answer": "修复后答案",
    "final_answer": "最终答案",
    "error_summary": "错误信息",
}

_INPUT_CONTRACTS: dict[str, list[str]] = {
    "preprocess_subgraph": ["user_input"],
    "merge_context": ["user_input", "recent_turns"],
    "resolve_reference": ["user_input"],
    "ambiguity_check": ["resolved_query"],
    "query_normalize": ["resolved_query"],
    "query_plan": ["normalized_query"],
    "decomposition": ["normalized_query"],
    "generate_variants": ["normalized_query"],
    "hyde": ["normalized_query"],
    "query_plan_finalize": ["normalized_query", "sub_queries", "multi_queries"],
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
    "answer_review": ["draft_answer"],
    "answer_review_fuse": ["review_results"],
    "answer_repair": ["draft_answer"],
    "answer_commit": ["candidate_answer"],
    "force_exit": ["exit_action", "candidate_answer"],
}

_OUTPUT_CONTRACTS: dict[str, list[str]] = {
    "preprocess_subgraph": ["decision", "reason", "next_node_label"],
    "merge_context": ["merged_context"],
    "resolve_reference": ["resolved_query"],
    "ambiguity_check": ["decision", "reason", "clarification_prompt"],
    "query_normalize": ["normalized_query"],
    "query_plan": ["decision", "reason", "next_node_label"],
    "decomposition": ["sub_queries"],
    "generate_variants": ["multi_queries"],
    "hyde": ["hyde_docs"],
    "query_plan_finalize": ["query_items"],
    "preprocess_exit": ["next_node_label", "final_answer"],
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
    "answer_review": ["decision", "reason", "next_node_label"],
    "answer_review_fuse": ["decision", "reason", "next_node_label"],
    "answer_repair": ["repaired_answer"],
    "answer_commit": ["final_answer"],
    "force_exit": ["final_answer"],
}





def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _non_empty_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _pick_text(snapshot: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        text = _non_empty_text(snapshot.get(key))
        if text:
            return text
    return None


def _pick_string_list(snapshot: Mapping[str, Any], *keys: str) -> list[str] | None:
    for key in keys:
        raw = snapshot.get(key)
        if not isinstance(raw, list):
            continue
        items = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
        if items:
            return items
    return None


def _get_context_frame(snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
    return _as_dict(snapshot.get("context_frame"))


def _pick_context_frame_turns(
    snapshot: Mapping[str, Any], key: str
) -> list[str] | None:
    frame = _get_context_frame(snapshot)
    raw = frame.get(key) if frame else None
    if not isinstance(raw, list):
        return None
    turns: list[str] = []
    for item in raw:
        record = _as_dict(item)
        if not record:
            continue
        role_raw = _non_empty_text(record.get("role")) or ""
        role = (
            "用户"
            if role_raw == "user"
            else "助手"
            if role_raw == "assistant"
            else role_raw
        )
        text = _non_empty_text(record.get("text"))
        if not text:
            continue
        turns.append(f"{role}: {text}" if role else text)
    return turns or None


def _summary_for_node(snapshot: Mapping[str, Any], node_name: str) -> dict[str, Any]:
    stage_summaries = _as_dict(snapshot.get("stage_summaries")) or {}
    return (
        _as_dict(stage_summaries.get(_NODE_SUMMARY_KEY_MAP.get(node_name, node_name)))
        or {}
    )


def _resolve_trace_command(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return _as_dict(snapshot.get("__trace_command__")) or {}


def _resolve_routing_decision(
    snapshot: Mapping[str, Any], phase: str
) -> dict[str, Any]:
    routing = _as_dict(snapshot.get("routing_decisions")) or {}
    return _as_dict(routing.get(phase)) or {}


def _resolve_ambiguity_reason(
    *,
    summary: Mapping[str, Any],
    reflection: Mapping[str, Any],
    default_reason: str,
) -> str:
    ambiguous = summary.get("ambiguous")
    if ambiguous is None:
        ambiguous = _pick_text(reflection, "action") == "clarify"
    clarification_payload = _as_dict(summary.get("clarification_payload")) or {}
    model_reason = _pick_text(summary, "model_reason") or _pick_text(
        clarification_payload, "model_reason"
    )
    if model_reason:
        return model_reason

    reason_code = _pick_text(summary, "reason_code") or _pick_text(
        clarification_payload, "reason_code"
    )
    if reason_code:
        mapped = _AMBIGUITY_REASON_CODE_LABELS.get(reason_code.strip().lower())
        if mapped:
            return mapped

    summary_reason = _pick_text(summary, "reason")
    if (
        summary_reason
        and summary_reason.strip().lower() not in _AMBIGUITY_TECHNICAL_REASONS
    ):
        return summary_reason

    return (
        _AMBIGUITY_DEFAULT_REASON_TRUE
        if bool(ambiguous)
        else _AMBIGUITY_DEFAULT_REASON_FALSE
    ) or default_reason


def _resolve_query_plan_reason(
    *,
    summary: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    default_reason: str,
) -> str:
    reasoning = _pick_text(summary, "reasoning")
    if not reasoning and not _pick_text(summary, "failure_reason"):
        reasoning = _pick_text(
            _as_dict(snapshot.get("query_plan_result")) or {}, "reasoning"
        )
    if reasoning:
        return reasoning

    raw_strategy = (
        (
            _pick_text(summary, "strategy")
            or _pick_text(snapshot, "query_strategy")
            or _pick_text(summary, "goto")
            or ""
        )
        .strip()
        .lower()
    )
    if raw_strategy == "decomposition":
        if bool(summary.get("is_comparison")) or bool(summary.get("has_multi_target")):
            return _QUERY_PLAN_REASON_DECOMPOSITION
        return _QUERY_PLAN_REASON_DECOMPOSITION_GENERIC
    if raw_strategy in {"multi_query", "generate_variants"}:
        return _QUERY_PLAN_REASON_MULTI_QUERY
    if raw_strategy in {"direct", "simple", "query_plan_finalize"}:
        return _QUERY_PLAN_REASON_DIRECT
    return default_reason


def _resolve_doc_gate_round(snapshot: Mapping[str, Any]) -> int | None:
    task = _as_dict(snapshot.get("doc_gate_task")) or {}
    raw_round = task.get("round")
    if isinstance(raw_round, int) and raw_round > 0:
        return raw_round
    state_round = snapshot.get("doc_gate_round")
    if isinstance(state_round, int) and state_round > 0:
        return state_round
    return None


def _resolve_doc_gate_run(
    snapshot: Mapping[str, Any], node_name: str
) -> dict[str, Any]:
    gate = _DOC_GATE_NODE_TO_GATE.get(node_name)
    if not gate:
        return {}
    active_round = _resolve_doc_gate_round(snapshot)
    runs = snapshot.get("doc_gate_runs")
    candidates = (
        [item for item in runs if isinstance(item, dict)]
        if isinstance(runs, list)
        else []
    )
    for item in reversed(candidates):
        if str(item.get("gate") or "") != gate:
            continue
        round_value = item.get("round")
        if (
            active_round is None
            or not isinstance(round_value, int)
            or round_value == active_round
        ):
            return item
    return {}


def _resolve_answer_review_round(snapshot: Mapping[str, Any]) -> int | None:
    task = _as_dict(snapshot.get("answer_review_task")) or {}
    raw_round = task.get("review_round")
    if isinstance(raw_round, int) and raw_round >= 0:
        return raw_round
    loop_counts = _as_dict(snapshot.get("loop_counts")) or {}
    state_round = loop_counts.get("generation_retries")
    if isinstance(state_round, int) and state_round >= 0:
        return state_round
    dispatch_summary = _summary_for_node(snapshot, "answer_review_dispatch")
    summary_round = dispatch_summary.get("review_round")
    if isinstance(summary_round, int) and summary_round >= 0:
        return summary_round
    return None


def _resolve_answer_review_run(
    snapshot: Mapping[str, Any], node_name: str
) -> dict[str, Any]:
    check = _ANSWER_REVIEW_NODE_TO_CHECK.get(node_name)
    if not check:
        return {}
    active_round = _resolve_answer_review_round(snapshot)
    runs = snapshot.get("answer_review_runs")
    candidates = (
        [item for item in runs if isinstance(item, dict)]
        if isinstance(runs, list)
        else []
    )
    for item in reversed(candidates):
        if str(item.get("check") or "") != check:
            continue
        run_round = item.get("review_round")
        if isinstance(run_round, int):
            if active_round is None or run_round == active_round:
                return item
            continue
        if active_round in {None, 0}:
            return item
    return {}


def _resolve_current_subquery_run(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    runs = snapshot.get("subquery_runs")
    candidates = (
        [item for item in runs if isinstance(item, dict)]
        if isinstance(runs, list)
        else []
    )
    if not candidates:
        return {}

    task = _as_dict(snapshot.get("subquery_task")) or {}
    task_id = _non_empty_text(task.get("subquery_id"))
    task_index = task.get("index")
    if task_id:
        for item in reversed(candidates):
            if _non_empty_text(item.get("subquery_id")) == task_id:
                return item
    if isinstance(task_index, int):
        for item in reversed(candidates):
            if item.get("index") == task_index:
                return item
    return candidates[-1]


def _format_query_items(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    items: list[str] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, str) and item.strip():
            items.append(f"{index}. {item.strip()}")
            continue
        record = _as_dict(item)
        if not record:
            continue
        query = _non_empty_text(record.get("query"))
        if not query:
            continue
        kind = _non_empty_text(record.get("kind"))
        prefix = f"[{kind}] " if kind else ""
        items.append(f"{index}. {prefix}{query}")
    return items or None


def _extract_query_texts_by_kind(
    snapshot: Mapping[str, Any],
    *kinds: str,
) -> list[str] | None:
    raw_items = snapshot.get("query_items")
    if not isinstance(raw_items, list):
        return None
    allowed = {
        kind.strip().lower() for kind in kinds if isinstance(kind, str) and kind.strip()
    }
    if not allowed:
        return None
    items: list[str] = []
    for item in raw_items:
        record = _as_dict(item)
        if not record:
            continue
        raw_kind = _pick_text(record, "kind")
        if not raw_kind or raw_kind.strip().lower() not in allowed:
            continue
        if raw_kind.strip().lower() == "hyde":
            hyde_queries = _pick_string_list(record, "hyde_queries")
            if hyde_queries:
                items.extend(hyde_queries)
                continue
        query = _pick_text(record, "query")
        if query:
            items.append(query)
    return items or None


def _resolve_kind_breakdown_count(
    snapshot: Mapping[str, Any],
    *kinds: str,
) -> int:
    summary = _summary_for_node(snapshot, "query_plan_finalize")
    breakdown = _as_dict(summary.get("kind_breakdown")) or {}
    total = 0
    for kind in kinds:
        raw = breakdown.get(kind)
        if isinstance(raw, int) and raw > 0:
            total += raw
    return total


def _resolve_sub_queries_display(snapshot: Mapping[str, Any]) -> list[str] | None:
    explicit = _pick_string_list(snapshot, "sub_queries")
    if explicit:
        return explicit

    decomposition_plan = _as_dict(snapshot.get("decomposition_plan")) or {}
    specs = decomposition_plan.get("sub_query_specs")
    if isinstance(specs, list):
        queries = [
            query
            for spec in specs
            if isinstance(spec, dict)
            for query in [_pick_text(spec, "query")]
            if query
        ]
        if queries:
            return queries

    from_query_items = _extract_query_texts_by_kind(snapshot, "subquery")
    if from_query_items:
        return from_query_items

    subquery_count = _resolve_kind_breakdown_count(snapshot, "subquery")
    if subquery_count > 0:
        return [f"共 {subquery_count} 个分解问题（trace 未记录明细）"]

    strategy = (
        _pick_text(_as_dict(snapshot.get("query_plan_result")) or {}, "strategy")
        or _pick_text(_summary_for_node(snapshot, "query_plan"), "strategy")
        or _pick_text(snapshot, "query_strategy")
    )
    if (strategy or "").strip().lower() == "decomposition":
        return ["已进入问题拆解，trace 未记录明细"]
    return None


def _resolve_multi_queries_display(snapshot: Mapping[str, Any]) -> list[str] | None:
    explicit = _pick_string_list(snapshot, "multi_queries")
    if explicit:
        return explicit

    from_query_items = _extract_query_texts_by_kind(snapshot, "variant", "paraphrase")
    if from_query_items:
        return from_query_items

    stage_count_candidates = [
        _summary_for_node(snapshot, "generate_variants").get("count"),
    ]
    for raw in stage_count_candidates:
        if isinstance(raw, int) and raw > 0:
            return [f"共 {raw} 条多路查询（trace 未记录明细）"]

    strategy = (
        _pick_text(_as_dict(snapshot.get("query_plan_result")) or {}, "strategy")
        or _pick_text(_summary_for_node(snapshot, "query_plan"), "strategy")
        or _pick_text(snapshot, "query_strategy")
    )
    if (strategy or "").strip().lower() in {"decomposition", "multi_query"}:
        return ["已生成多路查询，trace 未记录明细"]
    return None


def _resolve_hyde_docs_display(snapshot: Mapping[str, Any]) -> list[str] | None:
    explicit = _pick_string_list(snapshot, "hyde_docs")
    if explicit:
        return explicit

    single_doc = _pick_text(snapshot, "hyde_doc")
    if single_doc:
        return [single_doc]

    from_query_items = _extract_query_texts_by_kind(snapshot, "hyde")
    if from_query_items:
        return from_query_items

    hyde_summary = _summary_for_node(snapshot, "hyde")
    generated_count = hyde_summary.get("generated_count")
    if isinstance(generated_count, int) and generated_count > 0:
        return [f"共 {generated_count} 篇 HyDE 文档（trace 未记录正文）"]

    if hyde_summary:
        return ["本轮未生成 HyDE 文档，已沿原问题继续检索"]
    return None


def _items_from_contract(
    contract: list[str], values: Mapping[str, Any]
) -> list[DisplayItem]:
    items: list[DisplayItem] = []
    for key in contract:
        _append_display_item(items, key=key, value=values.get(key))
    error_item = values.get("error_summary")
    if error_item:
        _append_display_item(items, key="error_summary", value=error_item)
    return items


def _append_display_item(items: list[DisplayItem], *, key: str, value: Any) -> None:
    if isinstance(value, bool):
        items.append(
            {
                "key": key,
                "label": _DISPLAY_LABELS[key],
                "value": "是" if value else "否",
            }
        )
        return
    if isinstance(value, (int, float)):
        items.append({"key": key, "label": _DISPLAY_LABELS[key], "value": str(value)})
        return
    if isinstance(value, str):
        text = _non_empty_text(value)
        if text:
            items.append({"key": key, "label": _DISPLAY_LABELS[key], "value": text})
        return
    if isinstance(value, list):
        lines = [item for item in value if isinstance(item, str) and item.strip()]
        if lines:
            items.append({"key": key, "label": _DISPLAY_LABELS[key], "value": lines})


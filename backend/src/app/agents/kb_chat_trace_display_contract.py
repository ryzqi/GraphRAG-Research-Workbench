"""KB Chat trace node display contract helpers."""

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
    "entity_expand": "实体扩展",
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
    "entity_expand": ["normalized_query", "multi_queries"],
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
    "entity_expand": ["multi_queries"],
    "hyde": ["hyde_docs"],
    "query_plan_finalize": ["query_items"],
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
    "answer_review": ["decision", "reason", "next_node_label"],
    "answer_review_fuse": ["decision", "reason", "next_node_label"],
    "answer_repair": ["repaired_answer"],
    "answer_commit": ["final_answer"],
    "force_exit": [],
}


def build_node_input_display_items(
    *,
    node_name: str,
    snapshot: Any,
    node_label_resolver: NodeLabelResolver | None = None,
) -> list[DisplayItem]:
    state = _as_dict(snapshot) or {}
    values = _build_input_value_map(
        node_name=node_name,
        snapshot=state,
        node_label_resolver=node_label_resolver,
    )
    return _items_from_contract(_INPUT_CONTRACTS.get(node_name, []), values)


def build_node_output_display_items(
    *,
    node_name: str,
    snapshot: Any,
    error_summary: str | None = None,
    node_label_resolver: NodeLabelResolver | None = None,
) -> list[DisplayItem]:
    state = _as_dict(snapshot) or {}
    values = _build_output_value_map(
        node_name=node_name,
        snapshot=state,
        error_summary=error_summary,
        node_label_resolver=node_label_resolver,
    )
    return _items_from_contract(_OUTPUT_CONTRACTS.get(node_name, []), values)


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
        items = [
            item.strip()
            for item in raw
            if isinstance(item, str) and item.strip()
        ]
        if items:
            return items
    return None


def _get_context_frame(snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
    return _as_dict(snapshot.get("context_frame"))


def _pick_context_frame_turns(snapshot: Mapping[str, Any], key: str) -> list[str] | None:
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
        role = "用户" if role_raw == "user" else "助手" if role_raw == "assistant" else role_raw
        text = _non_empty_text(record.get("text"))
        if not text:
            continue
        turns.append(f"{role}: {text}" if role else text)
    return turns or None


def _summary_for_node(snapshot: Mapping[str, Any], node_name: str) -> dict[str, Any]:
    stage_summaries = _as_dict(snapshot.get("stage_summaries")) or {}
    return _as_dict(stage_summaries.get(_NODE_SUMMARY_KEY_MAP.get(node_name, node_name))) or {}


def _resolve_trace_command(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return _as_dict(snapshot.get("__trace_command__")) or {}


def _resolve_routing_decision(snapshot: Mapping[str, Any], phase: str) -> dict[str, Any]:
    routing = _as_dict(snapshot.get("routing_decisions")) or {}
    return _as_dict(routing.get(phase)) or {}


def _resolve_ambiguity_reason(
    *,
    summary: Mapping[str, Any],
    reflection: Mapping[str, Any],
    default_reason: str,
) -> str:
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

    return (
        _pick_text(summary, "reason")
        or _pick_text(reflection, "reason")
        or default_reason
    )


def _resolve_doc_gate_round(snapshot: Mapping[str, Any]) -> int | None:
    task = _as_dict(snapshot.get("doc_gate_task")) or {}
    raw_round = task.get("round")
    if isinstance(raw_round, int) and raw_round > 0:
        return raw_round
    state_round = snapshot.get("doc_gate_round")
    if isinstance(state_round, int) and state_round > 0:
        return state_round
    return None


def _resolve_doc_gate_run(snapshot: Mapping[str, Any], node_name: str) -> dict[str, Any]:
    gate = _DOC_GATE_NODE_TO_GATE.get(node_name)
    if not gate:
        return {}
    active_round = _resolve_doc_gate_round(snapshot)
    runs = snapshot.get("doc_gate_runs")
    candidates = [item for item in runs if isinstance(item, dict)] if isinstance(runs, list) else []
    for item in reversed(candidates):
        if str(item.get("gate") or "") != gate:
            continue
        round_value = item.get("round")
        if active_round is None or not isinstance(round_value, int) or round_value == active_round:
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


def _resolve_answer_review_run(snapshot: Mapping[str, Any], node_name: str) -> dict[str, Any]:
    check = _ANSWER_REVIEW_NODE_TO_CHECK.get(node_name)
    if not check:
        return {}
    active_round = _resolve_answer_review_round(snapshot)
    runs = snapshot.get("answer_review_runs")
    candidates = [item for item in runs if isinstance(item, dict)] if isinstance(runs, list) else []
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
    candidates = [item for item in runs if isinstance(item, dict)] if isinstance(runs, list) else []
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
    allowed = {kind.strip().lower() for kind in kinds if isinstance(kind, str) and kind.strip()}
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
        _summary_for_node(snapshot, "entity_expand").get("count"),
        _summary_for_node(snapshot, "entity_expand").get("expanded_count"),
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

    fallback_policy = _as_dict((_as_dict(snapshot.get("query_plan_result")) or {}).get("fallback_policy")) or {}
    entity_expand_summary = _summary_for_node(snapshot, "entity_expand")
    if bool(fallback_policy.get("allow_hyde")) or bool(entity_expand_summary.get("hyde_enabled")):
        return ["已启用 HyDE，trace 未记录文档正文"]
    return None


def _build_input_value_map(
    *,
    node_name: str,
    snapshot: Mapping[str, Any],
    node_label_resolver: NodeLabelResolver | None,
) -> dict[str, Any]:
    _ = node_label_resolver
    current_subquery_run = _resolve_current_subquery_run(snapshot)
    values: dict[str, Any] = {
        "user_input": _pick_text(snapshot, "user_input"),
        "recent_turns": _pick_context_frame_turns(snapshot, "recent_turns"),
        "resolved_query": _pick_text(
            snapshot,
            "resolved_query",
            "coref_query",
            "rewrite_input_query",
            "user_input",
        ),
        "normalized_query": _pick_text(
            snapshot,
            "normalized_query",
            "resolved_query",
            "coref_query",
            "rewrite_input_query",
            "user_input",
        ),
        "query_items": _format_query_items(snapshot.get("query_items")),
        "draft_answer": _pick_text(snapshot, "draft_answer", "final_answer"),
        "current_evidence": _format_evidence_from_snapshot(snapshot),
        "subquery": _pick_text(
            _as_dict(snapshot.get("subquery_task")) or current_subquery_run,
            "query",
        ),
        "exit_action": _resolve_exit_action(snapshot),
        "candidate_answer": _pick_text(
            snapshot,
            "candidate_answer",
            "best_answer",
            "draft_answer",
            "final_answer",
        ),
        "gate_results": _format_gate_results(snapshot),
        "review_results": _format_review_results(snapshot),
        "sub_queries": _resolve_sub_queries_display(snapshot),
        "multi_queries": _resolve_multi_queries_display(snapshot),
        "final_answer": _pick_text(snapshot, "final_answer"),
        "retrieved_evidence": _format_evidence_for_node(node_name=node_name, snapshot=snapshot),
    }
    if node_name in {"merge_subquery_context", "context_compress"}:
        values["retrieved_evidence"] = _format_evidence_from_snapshot(snapshot)
    if node_name == "retrieve_subquery":
        values["subquery"] = _pick_text(current_subquery_run, "query") or values["subquery"]
    if node_name == "answer_review_fuse":
        values["review_results"] = _format_review_results(snapshot)
    return values


def _build_output_value_map(
    *,
    node_name: str,
    snapshot: Mapping[str, Any],
    error_summary: str | None,
    node_label_resolver: NodeLabelResolver | None,
) -> dict[str, Any]:
    summary = _summary_for_node(snapshot, node_name)
    decision, reason, next_node_label = _resolve_decision_triplet(
        node_name=node_name,
        snapshot=snapshot,
        summary=summary,
        node_label_resolver=node_label_resolver,
    )
    values: dict[str, Any] = {
        "decision": decision,
        "reason": reason,
        "next_node_label": next_node_label,
        "merged_context": _resolve_merged_context_display(snapshot),
        "resolved_query": _pick_text(
            snapshot,
            "resolved_query",
            "coref_query",
            "rewrite_input_query",
            "user_input",
        ),
        "normalized_query": _pick_text(
            snapshot,
            "normalized_query",
            "resolved_query",
            "coref_query",
            "rewrite_input_query",
            "user_input",
        ),
        "clarification_prompt": _pick_text(snapshot, "final_answer", "clarification_prompt"),
        "multi_queries": _resolve_multi_queries_display(snapshot),
        "sub_queries": _resolve_sub_queries_display(snapshot),
        "hyde_docs": _resolve_hyde_docs_display(snapshot),
        "query_items": _format_query_items(snapshot.get("query_items")),
        "planned_query_count": _resolve_planned_query_count(snapshot, summary),
        "planned_per_query_top_k": _resolve_planned_top_k(summary),
        "dispatch_targets": _resolve_dispatch_targets(
            node_name=node_name,
            snapshot=snapshot,
            node_label_resolver=node_label_resolver,
        ),
        "retrieved_evidence": _format_evidence_for_node(node_name=node_name, snapshot=snapshot),
        "merged_evidence": _format_evidence_from_snapshot(snapshot),
        "compressed_evidence": _format_compressed_evidence(snapshot),
        "review_checks": _format_review_checks(snapshot, node_label_resolver=node_label_resolver),
        "draft_answer": _pick_text(snapshot, "draft_answer"),
        "repaired_answer": _pick_text(snapshot, "repaired_answer", "final_answer"),
        "final_answer": _pick_text(snapshot, "final_answer", "best_answer", "draft_answer"),
        "error_summary": _non_empty_text(error_summary),
    }
    if node_name == "transform_query" and summary.get("rewritten") is False:
        values["normalized_query"] = None
    if node_name == "answer_commit":
        values["final_answer"] = _pick_text(snapshot, "final_answer", "best_answer", "draft_answer")
    if node_name == "force_exit":
        values["next_node_label"] = "结束"
    return values


def _items_from_contract(contract: list[str], values: Mapping[str, Any]) -> list[DisplayItem]:
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
            {"key": key, "label": _DISPLAY_LABELS[key], "value": "是" if value else "否"}
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


def _resolve_exit_action(snapshot: Mapping[str, Any]) -> str | None:
    reflection = _as_dict(snapshot.get("reflection")) or {}
    return _pick_text(reflection, "action") or _pick_text(snapshot, "exit_action")


def _resolve_planned_query_count(snapshot: Mapping[str, Any], summary: Mapping[str, Any]) -> int | None:
    raw = summary.get("query_count")
    if isinstance(raw, int):
        return raw
    query_items = snapshot.get("query_items")
    if isinstance(query_items, list) and query_items:
        return len(query_items)
    return None


def _resolve_planned_top_k(summary: Mapping[str, Any]) -> int | None:
    raw = summary.get("per_query_top_k")
    return raw if isinstance(raw, int) else None


def _resolve_dispatch_targets(
    *,
    node_name: str,
    snapshot: Mapping[str, Any],
    node_label_resolver: NodeLabelResolver | None,
) -> list[str] | None:
    if node_name == "dispatch_subqueries":
        return _format_query_items(snapshot.get("query_items"))
    return None


def _format_review_checks(
    snapshot: Mapping[str, Any],
    *,
    node_label_resolver: NodeLabelResolver | None,
) -> list[str] | None:
    summary = _summary_for_node(snapshot, "answer_review_dispatch")
    checks = summary.get("checks")
    if not isinstance(checks, list):
        trace = _resolve_trace_command(snapshot)
        checks = trace.get("goto_targets")
    if not isinstance(checks, list):
        return None
    result: list[str] = []
    for item in checks:
        if not isinstance(item, str) or not item.strip():
            continue
        check_name = _ANSWER_REVIEW_NODE_TO_CHECK.get(item, item)
        result.append(
            _REVIEW_CHECK_LABELS.get(
                check_name,
                _resolve_node_label(item, node_label_resolver=node_label_resolver),
            )
        )
    return result or None


def _format_gate_results(snapshot: Mapping[str, Any]) -> list[str] | None:
    runs = snapshot.get("doc_gate_runs")
    if not isinstance(runs, list):
        return None
    active_round = _resolve_doc_gate_round(snapshot)
    result: list[str] = []
    for gate in ("sufficiency",):
        match = None
        for item in reversed(runs):
            if not isinstance(item, dict) or str(item.get("gate") or "") != gate:
                continue
            round_value = item.get("round")
            if active_round is None or not isinstance(round_value, int) or round_value == active_round:
                match = item
                break
        if not match:
            continue
        passed = bool(match.get("passed"))
        reason = _non_empty_text(match.get("reason")) or "未返回明确原因"
        result.append(
            f"{_GATE_LABELS.get(gate, gate)}：{'通过' if passed else '未通过'}｜原因：{reason}"
        )
    return result or None


def _format_review_results(snapshot: Mapping[str, Any]) -> list[str] | None:
    runs = snapshot.get("answer_review_runs")
    if not isinstance(runs, list):
        return None
    active_round = _resolve_answer_review_round(snapshot)
    result: list[str] = []
    for check in ("citation", "answer"):
        match = None
        for item in reversed(runs):
            if not isinstance(item, dict) or str(item.get("check") or "") != check:
                continue
            round_value = item.get("review_round")
            if active_round is None or not isinstance(round_value, int) or round_value == active_round:
                match = item
                break
        if not match:
            continue
        passed = bool(match.get("passed"))
        reason = _non_empty_text(match.get("reason")) or "未返回明确原因"
        result.append(
            f"{_REVIEW_CHECK_LABELS.get(check, check)}：{'通过' if passed else '未通过'}｜原因：{reason}"
        )
    return result or None


def _format_evidence_for_node(*, node_name: str, snapshot: Mapping[str, Any]) -> list[str] | None:
    if node_name == "retrieve_subquery":
        run = _resolve_current_subquery_run(snapshot)
        return _format_evidence_value(run.get("context"))
    return _format_evidence_from_snapshot(snapshot)


def _format_compressed_evidence(snapshot: Mapping[str, Any]) -> list[str] | None:
    return _format_evidence_value(snapshot.get("final_context"))


def _format_evidence_from_snapshot(snapshot: Mapping[str, Any]) -> list[str] | None:
    for key in (
        "current_evidence",
        "retrieved_evidence",
        "compressed_evidence",
        "evidence_items",
        "final_context",
        "compressed_context",
        "context",
    ):
        result = _format_evidence_value(snapshot.get(key))
        if result:
            return result
    return None


def _format_evidence_value(value: Any) -> list[str] | None:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        blocks = _parse_evidence_blocks(text)
        if blocks:
            return [_format_evidence_entry(None, body) for body in blocks]
        if text in {"（未找到相关内容）", "未检索到相关证据"}:
            return ["未检索到相关证据"]
        return [_format_evidence_entry(None, text)]
    if isinstance(value, list):
        if not value:
            return ["未检索到相关证据"]
        items: list[str] = []
        for item in value:
            if isinstance(item, str):
                nested = _format_evidence_value(item)
                if nested:
                    items.extend(nested)
                continue
            record = _as_dict(item)
            if not record:
                continue
            title = _pick_text(
                record,
                "citation_title",
                "title",
                "document_name",
                "document_title",
            )
            body = _pick_text(record, "excerpt", "chunk_content", "content", "text", "body")
            items.append(_format_evidence_entry(title, body))
        return items or ["未检索到相关证据"]
    record = _as_dict(value)
    if record:
        return _format_evidence_value([record])
    return None


def _parse_evidence_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    for match in _EVIDENCE_BLOCK_RE.finditer(text.strip()):
        body = _non_empty_text(match.group(2))
        if body:
            blocks.append(body)
    return blocks


def _format_evidence_entry(title: str | None, body: str | None) -> str:
    return (
        f"文档名：{title or '未命名文档'}\n"
        f"Chunk 内容：{body or '正文缺失'}"
    )


def _single_item_list(value: str | None) -> list[str] | None:
    return [value] if value else None


def _resolve_merged_context_display(snapshot: Mapping[str, Any]) -> str | None:
    direct = _pick_text(snapshot, "display_context")
    if direct:
        return direct
    merged_context = _pick_text(snapshot, "merged_context")
    if not merged_context:
        return None
    frame = _get_context_frame(snapshot) or {}
    if _non_empty_text(frame.get("summary_text")) or _non_empty_text(frame.get("memory_snippet")):
        return merged_context
    return None


def _resolve_decision_triplet(
    *,
    node_name: str,
    snapshot: Mapping[str, Any],
    summary: Mapping[str, Any],
    node_label_resolver: NodeLabelResolver | None,
) -> tuple[str | None, str | None, str | None]:
    trace = _resolve_trace_command(snapshot)
    reflection = _as_dict(snapshot.get("reflection")) or {}
    next_node_label = _resolve_next_node_label(
        node_name=node_name,
        snapshot=snapshot,
        summary=summary,
        node_label_resolver=node_label_resolver,
    )
    default_reason = "未返回明确原因"

    if node_name == "ambiguity_check":
        ambiguous = summary.get("ambiguous")
        if ambiguous is None:
            ambiguous = _pick_text(reflection, "action") == "clarify"
        decision = "需要澄清" if bool(ambiguous) else "无需澄清"
        reason = _resolve_ambiguity_reason(
            summary=summary,
            reflection=reflection,
            default_reason=default_reason,
        )
        return decision, reason, next_node_label

    if node_name == "query_plan":
        decision = _complexity_decision_text(summary=summary, snapshot=snapshot)
        reason = _pick_text(summary, "reasoning", "reason") or default_reason
        return decision, reason, next_node_label or "下游节点未知"

    if node_name == "preprocess_exit":
        route = _resolve_routing_decision(snapshot, "preprocess")
        raw_next = _pick_text(route, "next_node") or _pick_text(trace, "goto")
        decision = "直接给出答案" if raw_next == "force_exit" else _humanize_decision(raw_next)
        reason = _pick_text(route, "reason") or _pick_text(reflection, "reason") or default_reason
        return decision or "结束当前流程", reason, next_node_label or "结束"

    if node_name == "preprocess_subgraph":
        route = _resolve_routing_decision(snapshot, "preprocess")
        raw = _pick_text(route, "next_node", "action") or _pick_text(trace, "goto")
        decision = _humanize_decision(raw) or (
            f"进入{next_node_label}" if next_node_label and next_node_label != "结束" else "结束当前流程"
        )
        reason = _pick_text(route, "reason") or _pick_text(summary, "reason") or default_reason
        return decision, reason, next_node_label or "下游节点未知"

    if node_name == "retrieval_subgraph":
        decision = _humanize_decision(_pick_text(trace, "goto")) or "完成检索流程"
        reason = _pick_text(summary, "reason") or "已完成检索并进入答案生成"
        return decision, reason, next_node_label or "下游节点未知"

    if node_name == "answer_subgraph":
        routing = _resolve_routing_decision(snapshot, "answer_subgraph")
        raw = _pick_text(routing, "next_node", "action") or _pick_text(summary, "next_step") or _pick_text(trace, "goto")
        decision = _answer_route_decision_text(raw)
        reason = _pick_text(routing, "reason") or _pick_text(summary, "reason") or _pick_text(reflection, "reason") or default_reason
        return decision, reason, next_node_label or "下游节点未知"

    if node_name in {
        "answer_review_citation",
        "answer_review",
    }:
        run = _resolve_answer_review_run(snapshot, node_name)
        passed = run.get("passed")
        decision = "通过" if passed is True else "未通过" if passed is False else "未返回明确结论"
        reason = _pick_text(run, "reason") or default_reason
        return decision, reason, next_node_label or _resolve_node_label(
            "answer_review_fuse",
            node_label_resolver=node_label_resolver,
        ) or "下游节点未知"

    if node_name == "answer_review_fuse":
        passed = summary.get("passed")
        if passed is True:
            decision = "审查通过"
        elif passed is False:
            decision = "审查未通过"
        else:
            raw = _pick_text(summary, "next_step") or _pick_text(trace, "goto")
            decision = _answer_route_decision_text(raw)
        reason = _pick_text(summary, "reason") or default_reason
        return decision, reason, next_node_label or "下游节点未知"

    if node_name == "force_exit":
        reason = _pick_text(summary, "reason") or _pick_text(reflection, "reason") or default_reason
        return None, reason, "结束"

    decision = _humanize_decision(
        _pick_text(summary, "decision", "action", "goto")
        or _pick_text(trace, "goto")
    )
    reason = _pick_text(summary, "reason") or _pick_text(reflection, "reason") or default_reason
    return decision, reason, next_node_label


def _resolve_next_node_label(
    *,
    node_name: str,
    snapshot: Mapping[str, Any],
    summary: Mapping[str, Any],
    node_label_resolver: NodeLabelResolver | None,
) -> str | None:
    if node_name == "force_exit":
        return "结束"

    trace = _resolve_trace_command(snapshot)
    candidates: list[str | None] = []

    phase_by_node = {
        "preprocess_subgraph": "preprocess",
        "preprocess_exit": "preprocess",
        "answer_subgraph": "answer_subgraph",
        "answer_commit": "answer_subgraph",
    }
    phase = phase_by_node.get(node_name)
    if phase:
        routing = _resolve_routing_decision(snapshot, phase)
        candidates.extend(
            [
                _pick_text(routing, "next_node"),
                _pick_text(routing, "action"),
            ]
        )

    candidates.extend(
        [
            _pick_text(summary, "next_node", "next_step", "goto"),
            _pick_text(trace, "goto"),
        ]
    )

    if node_name in {
        "answer_review_citation",
        "answer_review",
    }:
        candidates.append("answer_review_fuse")

    for candidate in candidates:
        label = _resolve_node_label(candidate, node_label_resolver=node_label_resolver)
        if label:
            return label
    return None


def _resolve_node_label(
    node_name: str | None,
    *,
    node_label_resolver: NodeLabelResolver | None,
) -> str | None:
    raw = _non_empty_text(node_name)
    if not raw:
        return None
    key = raw.strip()
    lowered = key.lower()
    if callable(node_label_resolver):
        resolved = _non_empty_text(node_label_resolver(key))
        if resolved:
            return resolved
    if lowered in _BUSINESS_LABEL_FALLBACKS:
        return _BUSINESS_LABEL_FALLBACKS[lowered]
    if lowered in _REVIEW_CHECK_LABELS:
        return _REVIEW_CHECK_LABELS[lowered]
    if any("\u4e00" <= ch <= "\u9fff" for ch in key):
        return key
    return None


def _complexity_decision_text(
    *,
    summary: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> str:
    raw = (
        _pick_text(summary, "strategy")
        or _pick_text(snapshot, "query_strategy")
        or _pick_text(summary, "goto")
    )
    mapping = {
        "simple": "直接检索",
        "direct": "简单问题",
        "moderate": "中等问题",
        "multi_query": "中等问题",
        "generate_variants": "中等问题",
        "complex": "复杂问题",
        "decomposition": "复杂问题",
    }
    return mapping.get((raw or "").strip().lower(), "待判定问题")


def _answer_route_decision_text(raw: str | None) -> str:
    mapping = {
        "end": "审查通过",
        "answer_commit": "审查通过",
        "answer_review_fuse": "进入审查汇总",
        "answer_repair": "需要修复答案",
        "transform_query": "需要继续检索",
        "force_exit": "结束当前回答",
    }
    return mapping.get((raw or "").strip().lower(), _humanize_decision(raw) or "继续处理")


def _humanize_decision(raw: str | None) -> str | None:
    text = _non_empty_text(raw)
    if not text:
        return None
    lowered = text.strip().lower()
    mapping = {
        "retrieval_subgraph": "进入检索流程",
        "query_plan_finalize": "进入查询定稿",
        "answer_subgraph": "进入答案生成",
        "answer_review_fuse": "进入审查汇总",
        "answer_repair": "进入答案修复",
        "answer_commit": "提交答案",
        "end": "结束",
        "force_exit": "结束当前回答",
        "clarify": "需要补充信息",
        "retry": "继续检索",
        "transform_query": "改写后重试",
        "pass": "通过",
        "passed": "通过",
        "fail": "未通过",
        "failed": "未通过",
    }
    if lowered in mapping:
        return mapping[lowered]
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return text
    label = _BUSINESS_LABEL_FALLBACKS.get(lowered)
    if label:
        return f"进入{label}" if label != "结束" else label
    return None

"""KB Chat trace 节点输出展示契约。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agents.kb_chat_trace_display_shared import (
    DisplayItem,
    NodeLabelResolver,
    _ANSWER_REVIEW_NODE_TO_CHECK,
    _EVIDENCE_BLOCK_RE,
    _BUSINESS_LABEL_FALLBACKS,
    _OUTPUT_CONTRACTS,
    _REVIEW_CHECK_LABELS,
    _GATE_LABELS,
    _as_dict,
    _format_query_items,
    _items_from_contract,
    _non_empty_text,
    _pick_text,
    _resolve_ambiguity_reason,
    _resolve_answer_review_round,
    _resolve_answer_review_run,
    _resolve_current_subquery_run,
    _resolve_doc_gate_round,
    _resolve_query_plan_reason,
    _resolve_hyde_docs_display,
    _resolve_multi_queries_display,
    _resolve_routing_decision,
    _resolve_sub_queries_display,
    _resolve_trace_command,
    _summary_for_node,
)


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
        "clarification_prompt": _pick_text(
            snapshot, "final_answer", "clarification_prompt"
        ),
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
        "retrieved_evidence": _format_evidence_for_node(
            node_name=node_name, snapshot=snapshot
        ),
        "merged_evidence": _format_evidence_from_snapshot(snapshot),
        "compressed_evidence": _format_compressed_evidence(snapshot),
        "review_checks": _format_review_checks(
            snapshot, node_label_resolver=node_label_resolver
        ),
        "draft_answer": _pick_text(snapshot, "draft_answer"),
        "repaired_answer": _pick_text(snapshot, "repaired_answer", "final_answer"),
        "final_answer": _pick_text(
            snapshot, "final_answer", "best_answer", "draft_answer"
        ),
        "error_summary": _non_empty_text(error_summary),
    }
    if node_name == "transform_query" and summary.get("rewritten") is False:
        values["normalized_query"] = None
    if node_name == "answer_commit":
        values["final_answer"] = _pick_text(
            snapshot, "final_answer", "best_answer", "draft_answer"
        )
    if node_name == "force_exit":
        values["next_node_label"] = "结束"
    return values

def _resolve_exit_action(snapshot: Mapping[str, Any]) -> str | None:
    reflection = _as_dict(snapshot.get("reflection")) or {}
    return _pick_text(reflection, "action") or _pick_text(snapshot, "exit_action")


def _resolve_planned_query_count(
    snapshot: Mapping[str, Any], summary: Mapping[str, Any]
) -> int | None:
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
        label = _REVIEW_CHECK_LABELS.get(
            check_name,
            _resolve_node_label(item, node_label_resolver=node_label_resolver),
        )
        if label is not None:
            result.append(label)
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
            if (
                active_round is None
                or not isinstance(round_value, int)
                or round_value == active_round
            ):
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
            if (
                active_round is None
                or not isinstance(round_value, int)
                or round_value == active_round
            ):
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


def _format_evidence_for_node(
    *, node_name: str, snapshot: Mapping[str, Any]
) -> list[str] | None:
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
            body = _pick_text(
                record, "excerpt", "chunk_content", "content", "text", "body"
            )
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
    return f"文档名：{title or '未命名文档'}\nChunk 内容：{body or '正文缺失'}"


def _single_item_list(value: str | None) -> list[str] | None:
    return [value] if value else None


def _resolve_merged_context_display(snapshot: Mapping[str, Any]) -> str | None:
    direct = _pick_text(snapshot, "display_context")
    if direct:
        return direct
    return _pick_text(snapshot, "merged_context")


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
        reason = _resolve_query_plan_reason(
            summary=summary,
            snapshot=snapshot,
            default_reason=default_reason,
        )
        return decision, reason, next_node_label or "下游节点未知"

    if node_name == "preprocess_exit":
        return None, None, next_node_label or "结束"

    if node_name == "preprocess_subgraph":
        route = _resolve_routing_decision(snapshot, "preprocess")
        raw = _pick_text(route, "next_node", "action") or _pick_text(trace, "goto")
        decision = _humanize_decision(raw) or (
            f"进入{next_node_label}"
            if next_node_label and next_node_label != "结束"
            else "结束当前流程"
        )
        reason = (
            _pick_text(route, "reason")
            or _pick_text(summary, "reason")
            or default_reason
        )
        return decision, reason, next_node_label or "下游节点未知"

    if node_name == "retrieval_subgraph":
        decision = _humanize_decision(_pick_text(trace, "goto")) or "完成检索流程"
        reason = _pick_text(summary, "reason") or "已完成检索并进入答案生成"
        return decision, reason, next_node_label or "下游节点未知"

    if node_name == "answer_subgraph":
        routing = _resolve_routing_decision(snapshot, "answer_subgraph")
        raw = (
            _pick_text(routing, "next_node", "action")
            or _pick_text(summary, "next_step")
            or _pick_text(trace, "goto")
        )
        decision = _answer_route_decision_text(raw)
        reason = (
            _pick_text(routing, "reason")
            or _pick_text(summary, "reason")
            or _pick_text(reflection, "reason")
            or default_reason
        )
        return decision, reason, next_node_label or "下游节点未知"

    if node_name in {
        "answer_review_citation",
        "answer_review",
    }:
        run = _resolve_answer_review_run(snapshot, node_name)
        passed = run.get("passed")
        decision = (
            "通过"
            if passed is True
            else "未通过"
            if passed is False
            else "未返回明确结论"
        )
        reason = _pick_text(run, "reason") or default_reason
        return (
            decision,
            reason,
            next_node_label
            or _resolve_node_label(
                "answer_review_fuse",
                node_label_resolver=node_label_resolver,
            )
            or "下游节点未知",
        )

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
        reason = (
            _pick_text(summary, "reason")
            or _pick_text(reflection, "reason")
            or default_reason
        )
        return None, reason, "结束"

    decision = _humanize_decision(
        _pick_text(summary, "decision", "action", "goto") or _pick_text(trace, "goto")
    )
    reason = (
        _pick_text(summary, "reason")
        or _pick_text(reflection, "reason")
        or default_reason
    )
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
    return mapping.get(
        (raw or "").strip().lower(), _humanize_decision(raw) or "继续处理"
    )


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

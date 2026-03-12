"""Shared KB Chat node metadata and node_io wrappers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import inspect
import json
from typing import Any

from langchain_core.runnables import Runnable
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime
from langgraph.types import Command, Send

DisplayItemsBuilder = Callable[..., list[dict[str, Any]]]

KB_CHAT_NODE_METADATA: dict[str, dict[str, Any]] = {
    "preprocess_subgraph": {"label": "预处理子图", "phase": "preprocess", "order": 0},
    "merge_context": {"label": "上下文合并", "phase": "preprocess", "order": 1},
    "coref_rewrite": {"label": "指代消解", "phase": "preprocess", "order": 2},
    "AMBIGUITY_CHECK_ENABLED": {"label": "歧义检查开关", "phase": "preprocess", "order": 3},
    "ambiguity_check": {"label": "歧义判断", "phase": "preprocess", "order": 4},
    "normalize_rewrite": {"label": "问题规范", "phase": "preprocess", "order": 5},
    "complexity_classify": {"label": "复杂度分类", "phase": "route", "order": 6},
    "adaptive_routing": {"label": "自适应路由", "phase": "route", "order": 7},
    "simple_path": {"label": "简单路径", "phase": "route", "order": 8},
    "moderate_path": {"label": "中等路径", "phase": "route", "order": 9},
    "complex_path": {"label": "复杂路径", "phase": "route", "order": 10},
    "ENABLE_MULTI_QUERY_MOD": {"label": "中等多路开关", "phase": "enhance", "order": 11},
    "generate_variants_mod": {"label": "中等变体生成", "phase": "enhance", "order": 12},
    "ENABLE_DECOMPOSITION": {"label": "拆解开关", "phase": "enhance", "order": 13},
    "decomposition": {"label": "问题分解", "phase": "enhance", "order": 14},
    "ENABLE_MULTI_QUERY": {"label": "多路开关", "phase": "enhance", "order": 15},
    "generate_variants": {"label": "多路扩展", "phase": "enhance", "order": 16},
    "entity_expand": {"label": "实体扩展", "phase": "enhance", "order": 17},
    "ENABLE_HYDE": {"label": "HyDE开关", "phase": "enhance", "order": 18},
    "hyde": {"label": "HyDE扩展", "phase": "enhance", "order": 19},
    "prepare_messages": {"label": "消息整理", "phase": "enhance", "order": 20},
    "preprocess_exit": {"label": "预处理出口", "phase": "enhance", "order": 21},
    "retrieval_subgraph": {"label": "检索子图", "phase": "retrieve", "order": 22},
    "retrieval_budget_plan": {"label": "检索预算规划", "phase": "retrieve", "order": 23},
    "dispatch_subqueries": {"label": "子查询派发", "phase": "retrieve", "order": 24},
    "retrieve_subquery": {"label": "子查询检索", "phase": "retrieve", "order": 25},
    "merge_subquery_context": {"label": "子查询上下文合并", "phase": "retrieve", "order": 26},
    "retrieve": {"label": "知识检索", "phase": "retrieve", "order": 27},
    "context_compress": {"label": "上下文压缩", "phase": "retrieve", "order": 28},
    "evidence_gate_subgraph": {"label": "证据门控子图", "phase": "judge", "order": 29},
    "doc_gate_dispatch": {"label": "文档门控分发", "phase": "judge", "order": 30},
    "doc_gate_sufficiency": {"label": "证据充分度", "phase": "judge", "order": 31},
    "doc_gate_answerability": {"label": "可回答性", "phase": "judge", "order": 32},
    "doc_gate_conflict": {"label": "证据冲突检测", "phase": "judge", "order": 33},
    "doc_gate_fuse": {"label": "证据门控融合", "phase": "judge", "order": 34},
    "doc_gate_route": {"label": "文档判定", "phase": "judge", "order": 35},
    "transform_query": {"label": "查询改写", "phase": "retrieve", "order": 36},
    "answer_subgraph": {"label": "答案子图", "phase": "generate", "order": 37},
    "draft_generate": {"label": "草稿生成", "phase": "generate", "order": 38},
    "answer_review_dispatch": {"label": "审查分发", "phase": "verify", "order": 39},
    "answer_review_citation": {"label": "引用覆盖审查", "phase": "verify", "order": 40},
    "answer_review_factual": {"label": "事实正确性审查", "phase": "verify", "order": 41},
    "answer_review_answerability": {"label": "可回答性审查", "phase": "verify", "order": 42},
    "answer_review_fuse": {"label": "审查结果融合", "phase": "verify", "order": 43},
    "cove_check": {"label": "高风险验证判定", "phase": "verify", "order": 44},
    "chain_of_verification": {"label": "验证链", "phase": "verify", "order": 45},
    "claim_citation_check": {"label": "断言引用校验", "phase": "verify", "order": 46},
    "answer_repair": {"label": "答案修复", "phase": "verify", "order": 47},
    "answer_commit": {"label": "答案提交", "phase": "generate", "order": 48},
    "finalize": {"label": "答案整理", "phase": "finalize", "order": 49},
    "force_exit": {"label": "提前终止", "phase": "finalize", "order": 50},
    "confidence_calibrate": {"label": "置信度校准", "phase": "finalize", "order": 51},
}

# Backward-compatible aliases for callers migrated from local helpers.
KB_NODE_METADATA = KB_CHAT_NODE_METADATA

_NODE_SUMMARY_KEY_MAP: dict[str, str] = {
    "retrieve": "retrieval_layer",
    "draft_generate": "generator",
    "generate_variants_mod": "generate_variants",
    "answer_commit": "answer_subgraph",
}

_DOC_GATE_NODE_TO_GATE: dict[str, str] = {
    "doc_gate_sufficiency": "sufficiency",
    "doc_gate_answerability": "answerability",
    "doc_gate_conflict": "conflict",
}

_ANSWER_REVIEW_NODE_TO_CHECK: dict[str, str] = {
    "answer_review_citation": "citation",
    "answer_review_factual": "factual",
    "answer_review_answerability": "answerability",
}


def resolve_kb_chat_node_metadata(node_id: str) -> dict[str, Any]:
    metadata = KB_CHAT_NODE_METADATA.get(node_id)
    if metadata:
        return dict(metadata)
    return {"label": node_id, "phase": None, "order": None}


def _to_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, set):
        return list(value)
    for attr in ("model_dump", "dict", "to_dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                if attr == "model_dump":
                    return fn(mode="json")
                return fn()
            except Exception:
                pass
    content = getattr(value, "content", None)
    name = getattr(value, "name", None)
    if content is not None or name is not None:
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = str(name)
        if content is not None:
            payload["content"] = str(content)
        return payload
    return str(value)


def _to_json_compatible(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=_json_default))
    except Exception:
        return str(value)


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _non_empty_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _append_display_item(items: list[dict[str, Any]], *, key: str, label: str, value: Any) -> None:
    if isinstance(value, bool):
        items.append({"key": key, "label": label, "value": "是" if value else "否"})
    elif isinstance(value, (int, float)):
        items.append({"key": key, "label": label, "value": str(value)})
    elif isinstance(value, str):
        text = _non_empty_text(value)
        if text:
            items.append({"key": key, "label": label, "value": text})
    elif isinstance(value, list):
        lines = [str(item) for item in value if isinstance(item, str) and str(item).strip()]
        if lines:
            items.append({"key": key, "label": label, "value": lines})


def _append_if_missing(items: list[dict[str, Any]], *, key: str, label: str, value: Any) -> None:
    if any(item.get("key") == key for item in items):
        return
    _append_display_item(items, key=key, label=label, value=value)


def _build_snapshot_summary(snapshot: Any) -> dict[str, Any]:
    if isinstance(snapshot, dict):
        summary: dict[str, Any] = {"kind": "object", "key_count": len(snapshot), "keys": list(snapshot.keys())[:16]}
        for text_key in ("user_input", "normalized_query", "draft_answer", "final_answer"):
            text = snapshot.get(text_key)
            if isinstance(text, str):
                summary[f"{text_key}_chars"] = len(text)
        return summary
    if isinstance(snapshot, list):
        return {"kind": "array", "count": len(snapshot)}
    return {"kind": type(snapshot).__name__}


def _summary_key_for_node(node_name: str) -> str:
    return _NODE_SUMMARY_KEY_MAP.get(node_name, node_name)


def _record_to_lines(value: Any) -> list[str] | None:
    record = _as_dict(value)
    if not record:
        return None
    lines: list[str] = []
    for key, item in record.items():
        if isinstance(item, bool):
            lines.append(f"{key}: {'是' if item else '否'}")
        elif isinstance(item, (int, float)):
            lines.append(f"{key}: {item}")
        elif isinstance(item, str) and item.strip():
            lines.append(f"{key}: {item}")
    return lines or None


def _format_query_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, str) and item.strip():
            lines.append(f"{index}. {item}")
            continue
        item_dict = _as_dict(item)
        if not item_dict:
            continue
        query = _non_empty_text(item_dict.get("query"))
        if not query:
            continue
        kind = _non_empty_text(item_dict.get("kind"))
        prefix = f"[{kind}] " if kind else ""
        if kind == "hyde":
            hyde_queries = item_dict.get("hyde_queries")
            if isinstance(hyde_queries, list):
                count = len(
                    [
                        candidate
                        for candidate in hyde_queries
                        if isinstance(candidate, str) and candidate.strip()
                    ]
                )
                if count > 0:
                    prefix = f"[hyde x{count}] "
        lines.append(f"{index}. {prefix}{query}")
    return lines


def _resolve_doc_gate_round(snapshot: dict[str, Any]) -> int | None:
    task = _as_dict(snapshot.get("doc_gate_task")) or {}
    raw_round = task.get("round")
    if isinstance(raw_round, int) and raw_round > 0:
        return raw_round
    state_round = snapshot.get("doc_gate_round")
    if isinstance(state_round, int) and state_round > 0:
        return state_round
    return None


def _resolve_doc_gate_run(snapshot: dict[str, Any], node_name: str) -> dict[str, Any]:
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


def _resolve_answer_review_run(snapshot: dict[str, Any], node_name: str) -> dict[str, Any]:
    check = _ANSWER_REVIEW_NODE_TO_CHECK.get(node_name)
    if not check:
        return {}
    runs = snapshot.get("answer_review_runs")
    candidates = [item for item in runs if isinstance(item, dict)] if isinstance(runs, list) else []
    for item in reversed(candidates):
        if str(item.get("check") or "") == check:
            return item
    return {}


def _format_gate_breakdown(summary: dict[str, Any]) -> list[str] | None:
    lines: list[str] = []
    for gate in ("sufficiency", "answerability", "conflict"):
        gate_summary = _as_dict(summary.get(gate)) or {}
        if not gate_summary:
            continue
        parts: list[str] = []
        if "passed" in gate_summary:
            parts.append(f"通过={'是' if bool(gate_summary.get('passed')) else '否'}")
        if gate_summary.get("score") is not None:
            parts.append(f"分数={gate_summary.get('score')}")
        reason = _non_empty_text(gate_summary.get("reason"))
        if reason:
            parts.append(f"原因={reason}")
        if parts:
            lines.append(f"{gate}: {'; '.join(parts)}")
    return lines or None


def _format_review_breakdown(summary: dict[str, Any]) -> list[str] | None:
    review_breakdown = _as_dict(summary.get("review_breakdown")) or {}
    lines: list[str] = []
    for check in ("citation", "factual", "answerability"):
        check_summary = _as_dict(review_breakdown.get(check)) or {}
        if not check_summary:
            continue
        parts: list[str] = []
        if "passed" in check_summary:
            parts.append(f"通过={'是' if bool(check_summary.get('passed')) else '否'}")
        if check_summary.get("confidence") is not None:
            parts.append(f"置信度={check_summary.get('confidence')}")
        reason = _non_empty_text(check_summary.get("reason"))
        if reason:
            parts.append(f"原因={reason}")
        if parts:
            lines.append(f"{check}: {'; '.join(parts)}")
    return lines or None


def _command_trace(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, Command):
        return None
    goto = result.goto
    if isinstance(goto, str) and goto.strip():
        return {"goto": goto.strip()}
    if isinstance(goto, (list, tuple)):
        targets: list[str] = []
        for item in goto:
            if isinstance(item, str) and item.strip():
                targets.append(item.strip())
            elif isinstance(item, Send) and isinstance(item.node, str) and item.node.strip():
                targets.append(item.node.strip())
        if targets:
            return {"goto_targets": targets}
    return None


def _build_node_input_display_items(*, node_name: str, input_snapshot: Any) -> list[dict[str, Any]]:
    snapshot = _as_dict(input_snapshot) or {}
    items: list[dict[str, Any]] = []
    reflection = _as_dict(snapshot.get("reflection")) or {}

    if node_name in {"preprocess_subgraph", "merge_context"}:
        _append_display_item(items, key="user_input", label="用户问题", value=snapshot.get("user_input"))
    elif node_name == "coref_rewrite":
        _append_display_item(items, key="query", label="输入问题", value=snapshot.get("rewrite_input_query") or snapshot.get("user_input"))
    elif node_name in {
        "AMBIGUITY_CHECK_ENABLED",
        "ambiguity_check",
        "normalize_rewrite",
    }:
        _append_display_item(items, key="query", label="输入问题", value=snapshot.get("coref_query") or snapshot.get("rewrite_input_query") or snapshot.get("user_input"))
    elif node_name in {
        "complexity_classify",
        "adaptive_routing",
        "simple_path",
        "moderate_path",
        "complex_path",
        "ENABLE_MULTI_QUERY_MOD",
        "generate_variants_mod",
        "ENABLE_DECOMPOSITION",
        "decomposition",
        "ENABLE_MULTI_QUERY",
        "generate_variants",
        "entity_expand",
        "ENABLE_HYDE",
        "hyde",
        "prepare_messages",
        "preprocess_exit",
        "retrieval_subgraph",
        "retrieval_budget_plan",
        "dispatch_subqueries",
        "retrieve",
        "context_compress",
        "evidence_gate_subgraph",
        "doc_gate_dispatch",
        "doc_gate_sufficiency",
        "doc_gate_answerability",
        "doc_gate_conflict",
        "doc_gate_fuse",
        "doc_gate_route",
        "transform_query",
        "answer_subgraph",
        "draft_generate",
        "answer_review_dispatch",
        "answer_review_citation",
        "answer_review_factual",
        "answer_review_answerability",
        "answer_review_fuse",
        "cove_check",
        "chain_of_verification",
        "claim_citation_check",
        "answer_repair",
        "answer_commit",
        "finalize",
        "confidence_calibrate",
    }:
        _append_display_item(items, key="normalized_query", label="规范化问题", value=snapshot.get("normalized_query") or snapshot.get("coref_query") or snapshot.get("user_input"))
    elif node_name == "force_exit":
        _append_display_item(items, key="action", label="终止动作", value=reflection.get("action"))
        _append_display_item(items, key="reason", label="终止原因", value=reflection.get("reason"))
        _append_display_item(items, key="best_answer", label="候选答案", value=snapshot.get("best_answer") or snapshot.get("draft_answer"))

    query_items = _format_query_items(snapshot.get("query_items"))
    _append_if_missing(items, key="query_items", label="查询项", value=query_items)
    _append_if_missing(items, key="user_input", label="用户问题", value=snapshot.get("user_input"))
    _append_if_missing(items, key="final_context", label="当前上下文", value=snapshot.get("compressed_context") or snapshot.get("final_context"))
    _append_if_missing(items, key="draft_answer", label="当前答案草稿", value=snapshot.get("draft_answer"))
    if not items:
        _append_display_item(items, key="node_name", label="节点", value=node_name)
    return items


def _build_node_output_display_items(*, node_name: str, output_snapshot: Any, error_summary: str | None = None) -> list[dict[str, Any]]:
    snapshot = _as_dict(output_snapshot) or {}
    summary = _as_dict((_as_dict(snapshot.get("stage_summaries")) or {}).get(_summary_key_for_node(node_name))) or {}
    trace = _as_dict(snapshot.get("__trace_command__")) or {}
    reflection = _as_dict(snapshot.get("reflection")) or {}
    retrieval_metrics = _as_dict((_as_dict(snapshot.get("metrics")) or {}).get("retrieval_layer")) or {}
    items: list[dict[str, Any]] = []
    _append_display_item(items, key="route_to", label="下一跳", value=trace.get("goto"))
    _append_display_item(items, key="route_targets", label="派发目标", value=trace.get("goto_targets"))

    if node_name == "preprocess_subgraph":
        _append_display_item(items, key="query_strategy", label="查询策略", value=snapshot.get("query_strategy"))
        _append_display_item(items, key="preprocess_next", label="预处理出口", value=snapshot.get("preprocess_next"))
        _append_display_item(items, key="sub_queries", label="分解问题", value=snapshot.get("sub_queries"))
        _append_display_item(items, key="multi_queries", label="多路查询", value=snapshot.get("multi_queries"))
        _append_display_item(items, key="action", label="后续动作", value=reflection.get("action"))
    elif node_name == "retrieval_subgraph":
        context_compress_summary = _as_dict((_as_dict(snapshot.get("stage_summaries")) or {}).get("context_compress")) or {}
        _append_display_item(items, key="evidence_count", label="证据数量", value=retrieval_metrics.get("evidence_count"))
        _append_display_item(items, key="retrieval_count", label="检索命中数", value=retrieval_metrics.get("retrieval_count"))
        _append_display_item(items, key="truncated", label="是否压缩截断", value=context_compress_summary.get("truncated"))
        _append_display_item(items, key="compressed_context", label="压缩后上下文", value=snapshot.get("compressed_context") or snapshot.get("final_context"))
    elif node_name == "evidence_gate_subgraph":
        gate_scores = _as_dict(snapshot.get("doc_gate_scores")) or {}
        gate_state = _as_dict(snapshot.get("doc_gate_state")) or {}
        _append_display_item(items, key="decision", label="门控决策", value=gate_scores.get("decision"))
        _append_display_item(items, key="score", label="门控分数", value=gate_scores.get("score") or gate_state.get("confidence"))
        _append_display_item(items, key="missing_gates", label="缺失门控", value=gate_scores.get("missing_gates"))
        _append_display_item(items, key="action", label="后续动作", value=reflection.get("action"))
        _append_display_item(items, key="reason", label="判定原因", value=gate_state.get("reason") or reflection.get("reason"))
    elif node_name == "answer_subgraph":
        _append_display_item(items, key="draft_answer", label="答案草稿", value=snapshot.get("draft_answer"))
        _append_display_item(items, key="final_answer", label="候选答案", value=snapshot.get("final_answer"))
        _append_display_item(items, key="best_answer", label="最佳答案", value=snapshot.get("best_answer"))
        _append_display_item(items, key="review_passed", label="审查是否通过", value=reflection.get("review_passed"))
        _append_display_item(items, key="review_risk_level", label="审查风险等级", value=reflection.get("review_risk_level"))
    elif node_name == "retrieval_budget_plan":
        for key, label in (
            ("complexity", "复杂度等级"),
            ("query_count", "查询数量"),
            ("per_query_top_k", "单查询 TopK"),
            ("global_candidates_limit", "候选上限"),
            ("rerank_input_limit", "重排输入上限"),
            ("failure_reason", "放宽原因"),
            ("retry_count", "重试次数"),
        ):
            _append_display_item(items, key=key, label=label, value=summary.get(key))
    elif node_name == "doc_gate_dispatch":
        _append_display_item(items, key="doc_gate_round", label="门控轮次", value=_resolve_doc_gate_round(snapshot))
    elif node_name in {"doc_gate_sufficiency", "doc_gate_answerability", "doc_gate_conflict"}:
        run = _resolve_doc_gate_run(snapshot, node_name)
        _append_display_item(items, key="passed", label="是否通过", value=run.get("passed"))
        _append_display_item(items, key="score", label="门控分数", value=run.get("score"))
        _append_display_item(items, key="reason", label="判定原因", value=run.get("reason"))
        extra = _as_dict(run.get("extra")) or {}
        if node_name == "doc_gate_sufficiency":
            _append_display_item(items, key="tokens", label="上下文 Token", value=extra.get("tokens"))
            _append_display_item(items, key="evidence_count", label="证据数量", value=extra.get("evidence_count"))
        elif node_name == "doc_gate_answerability":
            _append_display_item(items, key="overlap", label="词项重合数", value=extra.get("overlap"))
            _append_display_item(items, key="query_terms", label="问题词项数", value=extra.get("query_terms"))
        else:
            _append_display_item(items, key="conflict_markers", label="冲突标记数", value=extra.get("conflict_markers"))
    elif node_name == "doc_gate_fuse":
        _append_display_item(items, key="decision", label="融合决策", value=summary.get("decision"))
        _append_display_item(items, key="score", label="融合分数", value=summary.get("score"))
        _append_display_item(items, key="missing_gates", label="缺失门控", value=summary.get("missing_gates"))
        _append_display_item(items, key="gate_breakdown", label="门控明细", value=_format_gate_breakdown(summary))
    elif node_name == "doc_gate_route":
        _append_display_item(items, key="decision", label="文档决策", value=summary.get("decision"))
        _append_display_item(items, key="passed", label="相关性是否通过", value=summary.get("passed"))
        _append_display_item(items, key="action", label="后续动作", value=reflection.get("action"))
        _append_display_item(items, key="reason", label="判定原因", value=summary.get("reason"))
        _append_display_item(items, key="score", label="门控分数", value=summary.get("score") or summary.get("confidence"))
        _append_display_item(items, key="retry_advice", label="重试建议", value=summary.get("retry_advice"))
    elif node_name == "answer_review_dispatch":
        _append_display_item(items, key="check_count", label="审查项数量", value=summary.get("check_count"))
        _append_display_item(items, key="checks", label="审查项", value=summary.get("checks"))
    elif node_name in {"answer_review_citation", "answer_review_factual", "answer_review_answerability"}:
        run = _resolve_answer_review_run(snapshot, node_name)
        _append_display_item(items, key="passed", label="是否通过", value=run.get("passed"))
        _append_display_item(items, key="reason", label="判定原因", value=run.get("reason"))
        _append_display_item(items, key="confidence", label="审查置信度", value=run.get("confidence"))
        _append_display_item(items, key="decision_source", label="判定来源", value=run.get("decision_source"))
        _append_display_item(items, key="fallback_reason", label="降级原因", value=run.get("fallback_reason"))
        if node_name == "answer_review_citation":
            _append_display_item(items, key="citation_count", label="引用数量", value=run.get("citation_count"))
            _append_display_item(items, key="valid_citation_count", label="有效引用数量", value=run.get("valid_citation_count"))
            _append_display_item(items, key="invalid_citations", label="无效引用", value=run.get("invalid_citations"))
    elif node_name == "answer_review_fuse":
        _append_display_item(items, key="passed", label="审查是否通过", value=summary.get("passed"))
        _append_display_item(items, key="reason", label="判定原因", value=summary.get("reason"))
        _append_display_item(items, key="review_risk_level", label="审查风险等级", value=summary.get("review_risk_level"))
        _append_display_item(items, key="review_confidence", label="审查置信度", value=summary.get("review_confidence"))
        _append_display_item(items, key="review_decision_source", label="审查来源", value=summary.get("review_decision_source"))
        _append_display_item(items, key="best_answer", label="最佳答案", value=summary.get("best_answer") or snapshot.get("best_answer"))
        _append_display_item(items, key="review_breakdown", label="审查明细", value=_format_review_breakdown(summary))
    elif node_name == "cove_check":
        _append_display_item(items, key="high_risk", label="是否高风险问题", value=summary.get("high_risk"))
        _append_display_item(items, key="enabled", label="是否启用验证链", value=summary.get("enabled"))
    elif node_name == "chain_of_verification":
        _append_display_item(items, key="passed", label="验证链是否通过", value=summary.get("passed"))
        _append_display_item(items, key="reason", label="判定原因", value=summary.get("reason"))
        _append_display_item(items, key="citation_count", label="引用数量", value=summary.get("citation_count"))
    elif node_name == "claim_citation_check":
        _append_display_item(items, key="passed", label="断言校验是否通过", value=summary.get("passed"))
        _append_display_item(items, key="reason", label="判定原因", value=summary.get("reason"))
        _append_display_item(items, key="valid_citation_count", label="有效引用数量", value=summary.get("valid_citation_count"))
        _append_display_item(items, key="invalid_citations", label="无效引用", value=summary.get("invalid_citations"))
    elif node_name == "answer_commit":
        for key, label in (
            ("best_answer", "最佳答案"),
            ("degrade_reason", "降级原因"),
            ("repair_attempts", "修复次数"),
            ("generation_retries", "生成重试次数"),
            ("retrieval_retries", "检索重试次数"),
        ):
            _append_display_item(items, key=key, label=label, value=summary.get(key))
    elif node_name == "confidence_calibrate":
        for key, label in (
            ("confidence_score", "置信度分数"),
            ("confidence_level", "置信度等级"),
            ("gate_confidence", "门控置信度"),
            ("review_confidence", "审查置信度"),
            ("citation_score", "引用得分"),
            ("cove_passed", "验证链是否通过"),
            ("claim_check_passed", "断言校验是否通过"),
        ):
            _append_display_item(items, key=key, label=label, value=summary.get(key) if key in summary else snapshot.get(key))
    elif node_name == "entity_expand":
        _append_display_item(items, key="multi_queries", label="多路查询", value=snapshot.get("multi_queries"))
        _append_display_item(items, key="input_count", label="输入数量", value=summary.get("input_count"))
        _append_display_item(items, key="expanded_count", label="扩展后数量", value=summary.get("expanded_count"))
        _append_display_item(items, key="added_count", label="新增数量", value=summary.get("added_count"))
        _append_display_item(items, key="pruned_count", label="剪枝数量", value=summary.get("pruned_count"))
        _append_display_item(items, key="min_confidence", label="最低置信度", value=summary.get("min_confidence"))
        _append_display_item(items, key="drift_guardrail_triggered", label="是否命中漂移护栏", value=summary.get("drift_guardrail_triggered"))
        _append_display_item(items, key="fallback_reason", label="降级原因", value=summary.get("fallback_reason"))

    for key, label in (
        ("doc_gate_round", "门控轮次"),
        ("preprocess_next", "预处理出口"),
        ("normalized_query", "改写后问题"),
        ("final_answer", "最终答案"),
        ("draft_answer", "草稿答案"),
        ("confidence_score", "置信度分数"),
        ("confidence_level", "置信度等级"),
    ):
        _append_if_missing(items, key=key, label=label, value=snapshot.get(key) if key != "doc_gate_round" else _resolve_doc_gate_round(snapshot))
    _append_if_missing(items, key="sub_queries", label="分解问题", value=snapshot.get("sub_queries"))
    _append_if_missing(items, key="multi_queries", label="多路查询", value=snapshot.get("multi_queries"))
    _append_if_missing(items, key="summary", label="阶段摘要", value=_record_to_lines(summary))
    if error_summary:
        _append_display_item(items, key="error_summary", label="错误信息", value=error_summary)
    return items


def _build_event_base_payload(node_name: str) -> dict[str, Any]:
    return {
        "event_type": "node_io",
        "node_name": node_name,
        "node_id": node_name,
    }


def _resolve_display_builder(
    builder: DisplayItemsBuilder | None,
    fallback: DisplayItemsBuilder,
) -> DisplayItemsBuilder:
    return builder if callable(builder) else fallback


def _merge_result_snapshot(input_snapshot: Any, result: Any) -> dict[str, Any]:
    merged_snapshot = dict(input_snapshot) if isinstance(input_snapshot, dict) else {}
    result_update = result.update if isinstance(result, Command) else result
    if isinstance(result_update, dict):
        merged_snapshot.update(_to_json_compatible(result_update))
    elif result_update is not None:
        merged_snapshot["value"] = _to_json_compatible(result_update)
    trace = _command_trace(result)
    if trace:
        merged_snapshot["__trace_command__"] = trace
    return merged_snapshot


async def _trace_async(
    *,
    node_name: str,
    state: Any,
    executor: Callable[[], Any],
    build_input_display_items: DisplayItemsBuilder | None,
    build_output_display_items: DisplayItemsBuilder | None,
) -> Any:
    writer = None
    try:
        writer = get_stream_writer()
    except Exception:
        writer = None

    input_builder = _resolve_display_builder(build_input_display_items, _build_node_input_display_items)
    output_builder = _resolve_display_builder(build_output_display_items, _build_node_output_display_items)

    input_snapshot = _to_json_compatible(state)
    input_summary = _build_snapshot_summary(input_snapshot)
    display_input_items = input_builder(node_name=node_name, input_snapshot=input_snapshot)
    started_at = datetime.now(timezone.utc)

    if callable(writer):
        payload = {
            **_build_event_base_payload(node_name),
            "phase": "start",
            "input_summary": input_summary,
            "input_snapshot": input_snapshot,
            "ts": _to_iso_now(),
        }
        if display_input_items:
            payload["display_input_items"] = display_input_items
        writer(payload)

    try:
        maybe_result = executor()
        result = await maybe_result if inspect.isawaitable(maybe_result) else maybe_result
        merged_snapshot = _merge_result_snapshot(input_snapshot, result)
        output_summary = _build_snapshot_summary(merged_snapshot)
        display_output_items = output_builder(node_name=node_name, output_snapshot=merged_snapshot)
        if callable(writer):
            payload = {
                **_build_event_base_payload(node_name),
                "phase": "end",
                "input_summary": input_summary,
                "output_summary": output_summary,
                "output_snapshot": merged_snapshot,
                "latency_ms": max(0, int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)),
                "ts": _to_iso_now(),
            }
            if display_input_items:
                payload["display_input_items"] = display_input_items
            if display_output_items:
                payload["display_output_items"] = display_output_items
            writer(payload)
        return result
    except Exception as exc:
        if callable(writer):
            payload = {
                **_build_event_base_payload(node_name),
                "phase": "error",
                "input_summary": input_summary,
                "error_summary": str(exc),
                "latency_ms": max(0, int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)),
                "ts": _to_iso_now(),
                "display_output_items": output_builder(
                    node_name=node_name,
                    output_snapshot={},
                    error_summary=str(exc),
                ),
            }
            if display_input_items:
                payload["display_input_items"] = display_input_items
            writer(payload)
        raise


class _KbChatTracedRunnable(Runnable[Any, Any]):
    def __init__(
        self,
        *,
        node_name: str,
        runnable: Runnable[Any, Any],
        build_input_display_items: DisplayItemsBuilder | None,
        build_output_display_items: DisplayItemsBuilder | None,
    ) -> None:
        self._node_name = node_name
        self._runnable = runnable
        self._build_input_display_items = build_input_display_items
        self._build_output_display_items = build_output_display_items
        self.builder = getattr(runnable, "builder", None)

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return self._runnable.invoke(input, config=config, **kwargs)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return await _trace_async(
            node_name=self._node_name,
            state=input,
            executor=lambda: self._runnable.ainvoke(input, config=config, **kwargs),
            build_input_display_items=self._build_input_display_items,
            build_output_display_items=self._build_output_display_items,
        )


def wrap_kb_chat_node_with_io(
    node_name: str,
    node_callable: Any,
    *,
    build_input_display_items: DisplayItemsBuilder | None = None,
    build_output_display_items: DisplayItemsBuilder | None = None,
):
    if isinstance(node_callable, Runnable):
        return _KbChatTracedRunnable(
            node_name=node_name,
            runnable=node_callable,
            build_input_display_items=build_input_display_items,
            build_output_display_items=build_output_display_items,
        )

    try:
        signature = inspect.signature(node_callable)
    except (TypeError, ValueError):
        signature = None
    runtime_param = signature.parameters.get("runtime") if signature else None
    accepts_runtime = runtime_param is not None
    runtime_is_positional_only = bool(
        runtime_param and runtime_param.kind is inspect.Parameter.POSITIONAL_ONLY
    )

    async def _wrapped(state: dict[str, Any], runtime: Runtime[Any]) -> Any:
        if not accepts_runtime:
            def executor() -> Any:
                return node_callable(state)
        elif runtime_is_positional_only:
            def executor() -> Any:
                return node_callable(state, runtime)
        else:
            def executor() -> Any:
                return node_callable(state, runtime=runtime)

        return await _trace_async(
            node_name=node_name,
            state=state,
            executor=executor,
            build_input_display_items=build_input_display_items,
            build_output_display_items=build_output_display_items,
        )

    return _wrapped


wrap_node_with_io = wrap_kb_chat_node_with_io

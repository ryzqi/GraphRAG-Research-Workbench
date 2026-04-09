"""KB Chat agentic LangGraph：preprocess -> retrieval -> reflection -> answer。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict, cast
import json

from functools import partial

from langchain.tools import BaseTool
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import RetryPolicy

from app.agents.kb_chat_agentic_state import (
    build_graph_input_state,
    KbChatInternalState,
    KbChatInputState,
    KbChatOutputState,
    PreprocessRoutingInput,
    resolve_routing_decision,
)
from app.agents.kb_chat_memory import resolve_kb_chat_store_user_id
from app.agents.tool_calling.registry import ToolMeta
from app.core.settings import get_settings

from app.agents.answer_subgraph import build_answer_subgraph
from app.agents.kb_chat_trace_nodes import (
    extend_kb_chat_node_metadata,
    KB_CHAT_NODE_METADATA,
    wrap_kb_chat_node_with_io as shared_wrap_node_with_io,
)
from app.agents.preprocess_subgraph import build_preprocess_subgraph
from app.agents.retrieval_subgraph import build_retrieval_subgraph
from app.agents.kb_chat_agentic.tool_loop import force_exit_node
from app.agents.kb_chat_agentic.reflection import (
    route_after_answer_review,
    transform_query_for_retry,
)


_NODE_METADATA: dict[str, dict[str, Any]] = KB_CHAT_NODE_METADATA


class KbChatGraphContext(TypedDict, total=False):
    """通过 LangGraph context_schema 传递的运行期只读上下文。"""

    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def _route_after_preprocess_subgraph(state: PreprocessRoutingInput) -> str:
    decision = resolve_routing_decision(state, "preprocess")
    next_node = str(decision.get("next_node") or "").strip().lower()
    if next_node in {"retrieval_subgraph", "transform_query", "force_exit"}:
        return next_node
    return "retrieval_subgraph"


def build_kb_chat_run_config(
    *, thread_id: str | None, recursion_limit: int
) -> dict[str, Any]:
    """为 KB Chat 构建 LangGraph 调用配置。

    `recursion_limit` must stay at top-level config (not under `configurable`).
    """
    config: dict[str, Any] = {"recursion_limit": int(recursion_limit)}
    if thread_id:
        config["configurable"] = {"thread_id": thread_id}
    return config


def build_kb_chat_run_context(
    *,
    thread_id: str | None,
    state: dict[str, Any] | None,
    user_id: str | None = None,
    kb_ids: list[str] | None = None,
    runtime_config: dict[str, Any] | None = None,
    settings: Any,
) -> KbChatGraphContext:
    """为 context_schema 驱动的节点运行时数据构建上下文。"""

    state_obj = state if isinstance(state, dict) else {}
    memory_keys = state_obj.get("memory_keys")
    if not isinstance(memory_keys, dict):
        memory_keys = {}
    runtime_config_payload = (
        runtime_config
        if isinstance(runtime_config, dict)
        else state_obj.get("runtime_config")
    )
    if not isinstance(runtime_config_payload, dict):
        runtime_config_payload = {}
    kb_ids_payload = kb_ids if isinstance(kb_ids, list) else memory_keys.get("kb_ids")
    if not isinstance(kb_ids_payload, list):
        kb_ids_payload = []
    resolved_thread_id = str(thread_id or memory_keys.get("thread_id") or "")
    resolved_user_id = resolve_kb_chat_store_user_id(
        user_id=user_id if isinstance(user_id, str) else memory_keys.get("user_id"),
        thread_id=resolved_thread_id,
    )
    return {
        "thread_id": resolved_thread_id,
        "user_id": resolved_user_id,
        "kb_ids": [
            str(item)
            for item in kb_ids_payload
            if isinstance(item, str) and item.strip()
        ],
        "runtime_config": runtime_config_payload,
        "message_budget": {
            "max_candidates": int(
                runtime_config_payload.get("parallel_retrieval_max_branches")
                if isinstance(
                    runtime_config_payload.get("parallel_retrieval_max_branches"), int
                )
                else getattr(settings, "kb_chat_parallel_retrieval_max_branches", 6)
            ),
            "min_queries": int(
                runtime_config_payload.get("parallel_retrieval_min_queries")
                if isinstance(
                    runtime_config_payload.get("parallel_retrieval_min_queries"), int
                )
                else getattr(settings, "kb_chat_parallel_retrieval_min_queries", 2)
            ),
            "include_main": bool(
                runtime_config_payload.get("parallel_retrieval_include_main")
                if isinstance(
                    runtime_config_payload.get("parallel_retrieval_include_main"), bool
                )
                else getattr(settings, "kb_chat_parallel_retrieval_include_main", True)
            ),
        },
    }


def _to_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, set):
        return list(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except Exception:
            pass
    dict_fn = getattr(value, "dict", None)
    if callable(dict_fn):
        try:
            return dict_fn()
        except Exception:
            pass
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
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
        additional_kwargs = getattr(value, "additional_kwargs", None)
        if isinstance(additional_kwargs, dict) and additional_kwargs:
            payload["additional_kwargs"] = additional_kwargs
        return payload
    return str(value)


def _to_json_compatible(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=_json_default))
    except Exception:
        return str(value)


def _build_snapshot_summary(snapshot: Any) -> dict[str, Any]:
    if isinstance(snapshot, dict):
        summary: dict[str, Any] = {
            "kind": "object",
            "keys": list(snapshot.keys())[:16],
            "key_count": len(snapshot),
        }
        messages = snapshot.get("messages")
        if isinstance(messages, list):
            summary["messages_count"] = len(messages)
        for text_key in (
            "user_input",
            "merged_context",
            "normalized_query",
            "draft_answer",
            "final_answer",
        ):
            text = snapshot.get(text_key)
            if isinstance(text, str):
                summary[f"{text_key}_chars"] = len(text)
        return summary
    if isinstance(snapshot, list):
        return {"kind": "array", "count": len(snapshot)}
    return {"kind": type(snapshot).__name__}


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _non_empty_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if not value.strip():
        return None
    return value


def _bool_to_zh(value: bool) -> str:
    return "是" if value else "否"


def _pick_text(snapshot: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        text = _non_empty_text(snapshot.get(key))
        if text is not None:
            return text
    return None


def _pick_string_list(snapshot: dict[str, Any], *keys: str) -> list[str] | None:
    for key in keys:
        value = snapshot.get(key)
        if not isinstance(value, list):
            continue
        lines = [str(item) for item in value if isinstance(item, str) and item.strip()]
        if lines:
            return lines
    return None


def _current_retrieval_round(snapshot: dict[str, Any]) -> int:
    loop_counts = _as_dict(snapshot.get("loop_counts")) or {}
    raw_round = loop_counts.get("retrieval_retries")
    if isinstance(raw_round, int) and raw_round >= 0:
        return raw_round
    return 0


def _current_subquery_runs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    active_round = _current_retrieval_round(snapshot)
    runs = snapshot.get("subquery_runs")
    if not isinstance(runs, list):
        return []
    filtered: list[dict[str, Any]] = []
    for run in runs:
        run_obj = _as_dict(run)
        if not run_obj:
            continue
        run_round = run_obj.get("retrieval_round")
        if isinstance(run_round, int):
            if run_round != active_round:
                continue
        elif active_round > 0:
            continue
        filtered.append(run_obj)
    return filtered


def _resolve_current_subquery_run(snapshot: dict[str, Any]) -> dict[str, Any]:
    runs = _current_subquery_runs(snapshot)
    if not runs:
        return {}
    return runs[-1]


def _context_frame(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = snapshot.get("context_frame")
    return _as_dict(value) or {}


def _pick_context_frame_text(snapshot: dict[str, Any], key: str) -> str | None:
    frame = _context_frame(snapshot)
    return _non_empty_text(frame.get(key))


def _pick_context_frame_turns(snapshot: dict[str, Any], key: str) -> list[str] | None:
    frame = _context_frame(snapshot)
    raw = frame.get(key)
    if not isinstance(raw, list):
        return None
    lines: list[str] = []
    for item in raw:
        item_dict = _as_dict(item)
        if not item_dict:
            continue
        role_raw = _non_empty_text(item_dict.get("role")) or ""
        role = (
            "用户"
            if role_raw == "user"
            else "助手"
            if role_raw == "assistant"
            else role_raw
        )
        text = _non_empty_text(item_dict.get("text"))
        if not text:
            continue
        prefix = f"{role}: " if role else ""
        lines.append(f"{prefix}{text}")
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
                        value
                        for value in hyde_queries
                        if isinstance(value, str) and value.strip()
                    ]
                )
                if count > 0:
                    prefix = f"[hyde x{count}] "
        lines.append(f"{index}. {prefix}{query}")
    return lines


def _append_display_item(
    items: list[dict[str, Any]],
    *,
    key: str,
    label: str,
    value: Any,
) -> None:
    normalized: str | list[str] | None = None
    if isinstance(value, bool):
        normalized = _bool_to_zh(value)
    elif isinstance(value, (int, float)):
        normalized = str(value)
    elif isinstance(value, str):
        text = _non_empty_text(value)
        if text is not None:
            normalized = text
    elif isinstance(value, list):
        lines = [str(item) for item in value if isinstance(item, str) and item.strip()]
        if lines:
            normalized = lines
    if normalized is None:
        return
    items.append({"key": key, "label": label, "value": normalized})


def _summary_key_for_node(node_name: str) -> str:
    return {
        "retrieve": "retrieval_layer",
        "draft_generate": "generator",
        "answer_review_fuse": "answer_review",
    }.get(node_name, node_name)


def _resolve_node_summary(snapshot: dict[str, Any], node_name: str) -> dict[str, Any]:
    stage_summaries = _as_dict(snapshot.get("stage_summaries")) or {}
    candidate = stage_summaries.get(_summary_key_for_node(node_name))
    return _as_dict(candidate) or {}


def _resolve_reflection(snapshot: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(snapshot.get("reflection")) or {}


def _resolve_retrieval_metrics(snapshot: dict[str, Any]) -> dict[str, Any]:
    metrics = _as_dict(snapshot.get("metrics")) or {}
    retrieval_layer = metrics.get("retrieval_layer")
    return _as_dict(retrieval_layer) or {}


def _build_node_input_display_items(
    *,
    node_name: str,
    input_snapshot: Any,
) -> list[dict[str, Any]]:
    snapshot = _as_dict(input_snapshot) or {}
    if not snapshot:
        return []

    items: list[dict[str, Any]] = []
    reflection = _resolve_reflection(snapshot)

    if node_name == "merge_context":
        _append_display_item(
            items,
            key="user_input",
            label="用户问题",
            value=_pick_text(snapshot, "user_input"),
        )
    elif node_name == "resolve_reference":
        _append_display_item(
            items,
            key="query",
            label="输入问题",
            value=_pick_text(snapshot, "rewrite_input_query", "user_input"),
        )
    elif node_name in {"ambiguity_check", "query_normalize"}:
        _append_display_item(
            items,
            key="query",
            label="输入问题",
            value=_pick_text(
                snapshot,
                "resolved_query",
                "coref_query",
                "rewrite_input_query",
                "user_input",
            ),
        )
    elif node_name in {
        "query_plan",
        "decomposition",
        "generate_variants",
        "hyde",
    }:
        _append_display_item(
            items,
            key="normalized_query",
            label="规范化问题",
            value=_pick_text(
                snapshot,
                "normalized_query",
                "resolved_query",
                "coref_query",
                "user_input",
            ),
        )
    elif node_name == "query_plan_finalize":
        _append_display_item(
            items,
            key="normalized_query",
            label="主问题",
            value=_pick_text(
                snapshot,
                "normalized_query",
                "resolved_query",
                "coref_query",
                "user_input",
            ),
        )
        _append_display_item(
            items,
            key="query_strategy",
            label="消息策略",
            value=snapshot.get("query_strategy"),
        )
        _append_display_item(
            items,
            key="sub_queries",
            label="分解问题",
            value=_pick_string_list(snapshot, "sub_queries"),
        )
        _append_display_item(
            items,
            key="multi_queries",
            label="多路查询",
            value=_pick_string_list(snapshot, "multi_queries"),
        )
        hyde_docs = _pick_string_list(snapshot, "hyde_docs")
        if hyde_docs:
            _append_display_item(
                items,
                key="hyde_docs_count",
                label="HyDE 文档数量",
                value=len(hyde_docs),
            )
    elif node_name == "dispatch_subqueries":
        _append_display_item(
            items,
            key="query_strategy",
            label="查询策略",
            value=snapshot.get("query_strategy"),
        )
        _append_display_item(
            items,
            key="query_items",
            label="查询项",
            value=_format_query_items(snapshot.get("query_items")),
        )
    elif node_name == "retrieve_subquery":
        task = _as_dict(snapshot.get("subquery_task")) or {}
        _append_display_item(
            items,
            key="query",
            label="分支查询",
            value=_non_empty_text(task.get("query")),
        )
        _append_display_item(
            items,
            key="kind",
            label="分支类型",
            value=_non_empty_text(task.get("kind")),
        )
    elif node_name == "merge_subquery_context":
        current_runs = _current_subquery_runs(snapshot)
        _append_display_item(
            items,
            key="subquery_runs_count",
            label="分支结果数",
            value=len(current_runs) if current_runs else None,
        )
    elif node_name == "retrieve":
        query_items = _format_query_items(snapshot.get("query_items"))
        if query_items:
            _append_display_item(
                items,
                key="query_items",
                label="检索查询项",
                value=query_items,
            )
        else:
            _append_display_item(
                items,
                key="normalized_query",
                label="检索问题",
                value=_pick_text(
                    snapshot,
                    "normalized_query",
                    "resolved_query",
                    "coref_query",
                    "user_input",
                ),
            )
    elif node_name == "transform_query":
        _append_display_item(
            items,
            key="normalized_query",
            label="当前问题",
            value=_pick_text(
                snapshot,
                "normalized_query",
                "resolved_query",
                "coref_query",
                "user_input",
            ),
        )
        _append_display_item(
            items,
            key="reason",
            label="改写原因",
            value=reflection.get("reason"),
        )
    elif node_name == "force_exit":
        _append_display_item(
            items,
            key="action",
            label="终止动作",
            value=reflection.get("action"),
        )
        _append_display_item(
            items,
            key="reason",
            label="终止原因",
            value=reflection.get("reason"),
        )
        _append_display_item(
            items,
            key="best_answer",
            label="候选答案",
            value=_pick_text(snapshot, "best_answer", "draft_answer"),
        )

    return items


def _build_node_output_display_items(
    *,
    node_name: str,
    output_snapshot: Any,
    error_summary: str | None = None,
) -> list[dict[str, Any]]:
    snapshot = _as_dict(output_snapshot) or {}
    summary = _resolve_node_summary(snapshot, node_name)
    reflection = _resolve_reflection(snapshot)
    retrieval_metrics = _resolve_retrieval_metrics(snapshot)
    items: list[dict[str, Any]] = []

    if node_name == "merge_context":
        _append_display_item(
            items,
            key="current_question",
            label="用户问题",
            value=_pick_context_frame_text(snapshot, "current_question")
            or _pick_text(snapshot, "user_input"),
        )
        _append_display_item(
            items,
            key="recent_turns",
            label="最近对话",
            value=_pick_context_frame_turns(snapshot, "recent_turns"),
        )
        _append_display_item(
            items,
            key="merged_context",
            label="合并后上下文",
            value=_pick_text(snapshot, "merged_context"),
        )
        _append_display_item(
            items,
            key="memory_included",
            label="是否使用记忆",
            value=summary.get("memory_included"),
        )
        _append_display_item(
            items,
            key="summary_source",
            label="摘要来源",
            value=summary.get("summary_source"),
        )
        _append_display_item(
            items,
            key="compression_ratio",
            label="压缩比",
            value=summary.get("compression_ratio"),
        )
        _append_display_item(
            items,
            key="llm_resolve_used",
            label="冲突消解",
            value=summary.get("llm_resolve_used"),
        )
        _append_display_item(
            items,
            key="merge_fallback_used",
            label="回退启发式",
            value=summary.get("fallback_used"),
        )
    elif node_name == "resolve_reference":
        _append_display_item(
            items,
            key="resolved_query",
            label="改写后问题",
            value=_pick_text(snapshot, "resolved_query", "coref_query"),
        )
        _append_display_item(
            items,
            key="confidence",
            label="消解置信度",
            value=summary.get("confidence"),
        )
        _append_display_item(
            items,
            key="selected_mention",
            label="选择候选",
            value=summary.get("selected_mention"),
        )
        _append_display_item(
            items,
            key="rewritten",
            label="是否改写",
            value=summary.get("rewritten"),
        )
        _append_display_item(
            items,
            key="reason",
            label="改写原因",
            value=summary.get("reason"),
        )
        _append_display_item(
            items,
            key="needs_clarification_hint",
            label="建议先澄清",
            value=summary.get("needs_clarification_hint"),
        )
    elif node_name == "ambiguity_check":
        _append_display_item(
            items,
            key="ambiguous",
            label="是否歧义",
            value=summary.get("ambiguous"),
        )
        _append_display_item(
            items,
            key="reason",
            label="判定原因",
            value=summary.get("reason"),
        )
        _append_display_item(
            items,
            key="reason_code",
            label="原因编码",
            value=summary.get("reason_code"),
        )
        _append_display_item(
            items,
            key="confidence",
            label="歧义置信度",
            value=summary.get("confidence"),
        )
        _append_display_item(
            items,
            key="fallback_used",
            label="回退判定",
            value=summary.get("fallback_used"),
        )
        _append_display_item(
            items,
            key="action",
            label="后续动作",
            value=reflection.get("action"),
        )
        _append_display_item(
            items,
            key="final_answer",
            label="澄清提示",
            value=_pick_text(snapshot, "final_answer"),
        )
    elif node_name == "query_normalize":
        _append_display_item(
            items,
            key="normalized_query",
            label="规范化结果",
            value=_pick_text(snapshot, "normalized_query"),
        )
        _append_display_item(
            items,
            key="rewritten",
            label="是否变化",
            value=summary.get("rewritten"),
        )
    elif node_name == "query_plan":
        _append_display_item(
            items,
            key="query_strategy",
            label="路由策略",
            value=snapshot.get("query_strategy"),
        )
        _append_display_item(
            items,
            key="query_strategy_confidence",
            label="路由置信度",
            value=snapshot.get("query_strategy_confidence"),
        )
        _append_display_item(
            items,
            key="query_strategy_signals",
            label="风险信号",
            value=snapshot.get("query_strategy_signals"),
        )
        _append_display_item(
            items,
            key="decision_version",
            label="判定版本",
            value=summary.get("decision_version"),
        )
        _append_display_item(
            items,
            key="next_node",
            label="下一节点",
            value=summary.get("next_node"),
        )
    elif node_name == "decomposition":
        sub_queries = _pick_string_list(snapshot, "sub_queries")
        _append_display_item(
            items,
            key="sub_queries",
            label="分解问题",
            value=sub_queries,
        )
        _append_display_item(
            items,
            key="count",
            label="分解数量",
            value=summary.get("count")
            if summary.get("count") is not None
            else len(sub_queries or []),
        )
        _append_display_item(
            items,
            key="reason",
            label="分解原因",
            value=summary.get("reason"),
        )
    elif node_name == "generate_variants":
        multi_queries = _pick_string_list(snapshot, "multi_queries")
        _append_display_item(
            items,
            key="multi_queries",
            label="多路查询",
            value=multi_queries,
        )
        _append_display_item(
            items,
            key="count",
            label="查询数量",
            value=summary.get("count")
            if summary.get("count") is not None
            else len(multi_queries or []),
        )
        _append_display_item(
            items,
            key="reason",
            label="处理原因",
            value=summary.get("reason"),
        )
    elif node_name == "hyde":
        hyde_docs = _pick_string_list(snapshot, "hyde_docs")
        if hyde_docs:
            _append_display_item(
                items,
                key="hyde_docs_count",
                label="HyDE 文档数量",
                value=len(hyde_docs),
            )
        _append_display_item(
            items,
            key="requested_count",
            label="目标生成数量",
            value=summary.get("requested_count"),
        )
        _append_display_item(
            items,
            key="generated_count",
            label="实际生成数量",
            value=summary.get("generated_count"),
        )
        _append_display_item(
            items,
            key="retry_regenerated",
            label="是否重试重生",
            value=summary.get("retry_regenerated"),
        )
        _append_display_item(
            items,
            key="reason",
            label="处理原因",
            value=summary.get("reason"),
        )
    elif node_name == "query_plan_finalize":
        query_items = _format_query_items(snapshot.get("query_items"))
        _append_display_item(
            items,
            key="query_items",
            label="查询项",
            value=query_items,
        )
        _append_display_item(
            items,
            key="query_bundle_items_count",
            label="入选查询数",
            value=summary.get("query_count")
            if summary.get("query_count") is not None
            else len(query_items),
        )
        _append_display_item(
            items,
            key="candidate_count",
            label="候选查询数",
            value=summary.get("candidate_count"),
        )
        _append_display_item(
            items,
            key="selected_count",
            label="入选数量",
            value=summary.get("selected_count"),
        )
        _append_display_item(
            items,
            key="kind_breakdown",
            label="类型分布",
            value=summary.get("kind_breakdown"),
        )
        _append_display_item(
            items,
            key="fallback_reason",
            label="回退原因",
            value=summary.get("fallback_reason"),
        )
    elif node_name == "dispatch_subqueries":
        _append_display_item(
            items,
            key="mode",
            label="检索编排模式",
            value=summary.get("mode"),
        )
        _append_display_item(
            items,
            key="branch_count",
            label="并行分支数",
            value=summary.get("branch_count"),
        )
        _append_display_item(
            items,
            key="reason",
            label="编排原因",
            value=summary.get("reason"),
        )
        _append_display_item(
            items,
            key="rank_strategy",
            label="排序策略",
            value=summary.get("rank_strategy"),
        )
        _append_display_item(
            items,
            key="selected_queries",
            label="分支查询",
            value=summary.get("selected_queries"),
        )
    elif node_name == "retrieve_subquery":
        run = _resolve_current_subquery_run(snapshot)
        _append_display_item(
            items,
            key="query",
            label="分支查询",
            value=run.get("query"),
        )
        _append_display_item(
            items,
            key="kind",
            label="分支类型",
            value=run.get("kind"),
        )
        _append_display_item(
            items,
            key="success",
            label="检索是否成功",
            value=run.get("success"),
        )
        _append_display_item(
            items,
            key="retrieval_count",
            label="证据数量",
            value=run.get("retrieval_count"),
        )
        _append_display_item(
            items,
            key="reason",
            label="失败原因",
            value=run.get("reason"),
        )
    elif node_name == "merge_subquery_context":
        _append_display_item(
            items,
            key="mode",
            label="聚合模式",
            value=summary.get("mode"),
        )
        _append_display_item(
            items,
            key="branch_count",
            label="分支总数",
            value=summary.get("branch_count"),
        )
        _append_display_item(
            items,
            key="evidence_count",
            label="证据数量",
            value=summary.get("evidence_count"),
        )
        _append_display_item(
            items,
            key="retrieval_count",
            label="检索命中数",
            value=summary.get("retrieval_count"),
        )
        _append_display_item(
            items,
            key="failure_reasons",
            label="分支失败原因",
            value=summary.get("failure_reasons"),
        )
    elif node_name == "retrieve":
        _append_display_item(
            items,
            key="evidence_count",
            label="证据数量",
            value=retrieval_metrics.get("evidence_count")
            if retrieval_metrics.get("evidence_count") is not None
            else summary.get("evidence_count"),
        )
        _append_display_item(
            items,
            key="attempted",
            label="是否执行检索",
            value=retrieval_metrics.get("attempted")
            if retrieval_metrics.get("attempted") is not None
            else summary.get("attempted"),
        )
        _append_display_item(
            items,
            key="reason",
            label="检索说明",
            value=summary.get("reason"),
        )
        _append_display_item(
            items,
            key="retrieval_count",
            label="检索命中数",
            value=summary.get("retrieval_count"),
        )
        _append_display_item(
            items,
            key="query_used",
            label="检索查询",
            value=summary.get("query_used"),
        )
    elif node_name == "transform_query":
        _append_display_item(
            items,
            key="normalized_query",
            label="改写后问题",
            value=_pick_text(snapshot, "normalized_query", "coref_query"),
        )
        _append_display_item(
            items,
            key="rewritten",
            label="是否变化",
            value=summary.get("rewritten"),
        )
        _append_display_item(
            items,
            key="query_items",
            label="改写后查询项",
            value=_format_query_items(snapshot.get("query_items")),
        )
    elif node_name == "draft_generate":
        _append_display_item(
            items,
            key="draft_answer",
            label="生成草稿",
            value=_pick_text(snapshot, "draft_answer"),
        )
        _append_display_item(
            items,
            key="final_answer",
            label="候选答案",
            value=_pick_text(snapshot, "final_answer"),
        )
    elif node_name == "answer_review_fuse":
        _append_display_item(
            items,
            key="passed",
            label="答案审查是否通过",
            value=summary.get("passed"),
        )
        _append_display_item(
            items,
            key="action",
            label="后续动作",
            value=reflection.get("action"),
        )
        _append_display_item(
            items,
            key="reason",
            label="判定原因",
            value=summary.get("reason"),
        )
        _append_display_item(
            items,
            key="fallback_reason",
            label="回退原因",
            value=summary.get("fallback_reason"),
        )
        _append_display_item(
            items,
            key="best_answer",
            label="最佳答案",
            value=_pick_text(snapshot, "best_answer"),
        )
    elif node_name == "force_exit":
        _append_display_item(
            items,
            key="final_answer",
            label="终止输出",
            value=_pick_text(snapshot, "final_answer"),
        )
        _append_display_item(
            items,
            key="reason",
            label="终止原因",
            value=summary.get("reason"),
        )
        _append_display_item(
            items,
            key="used_best_answer",
            label="是否使用候选答案",
            value=summary.get("used_best_answer"),
        )

    if error_summary:
        _append_display_item(
            items,
            key="error_summary",
            label="错误信息",
            value=error_summary,
        )

    return items


def _wrap_node_with_io(node_name: str, node_callable: Any):
    return shared_wrap_node_with_io(node_name, node_callable)


class KbChatAgenticGraph:
    """Agentic KB Chat 图：preprocess → retrieval → reflection → answer。"""

    def __init__(
        self,
        *,
        chat_model: BaseChatModel,
        tools: list[BaseTool],
        tool_meta_by_name: dict[str, ToolMeta],  # kept for signature compatibility
        kb_chat_config: dict[str, Any] | None = None,
    ) -> None:
        del tool_meta_by_name  # not used in this stage (no human review)
        settings = get_settings()
        self._settings = settings
        transform_retry_policy = RetryPolicy(
            max_attempts=max(
                2, int(getattr(settings, "kb_chat_max_retrieval_retries", 2)) + 1
            )
        )

        def node_metadata(
            node_id: str,
            *,
            side_effect_type: str,
            retry_policy: RetryPolicy | None = None,
            retry_disabled_reason: str | None = None,
        ) -> dict[str, Any]:
            metadata = extend_kb_chat_node_metadata(
                node_id,
                side_effect_type=side_effect_type,
                retry_enabled=retry_policy is not None,
            )
            if retry_policy is None:
                metadata["retry_disabled_reason"] = (
                    retry_disabled_reason or side_effect_type
                )
            return metadata

        graph = StateGraph(
            state_schema=KbChatInternalState,
            context_schema=KbChatGraphContext,
            input_schema=KbChatInputState,
            output_schema=KbChatOutputState,
        )

        kb_tool = next(
            (t for t in tools if getattr(t, "name", None) == "kb_retrieve"), None
        )
        if kb_tool is None:
            raise RuntimeError("kb_retrieve tool is required for agentic KB chat")

        preprocess_subgraph = build_preprocess_subgraph(settings=settings)
        retrieval_subgraph = build_retrieval_subgraph(
            settings=settings,
            kb_tool=kb_tool,
            chat_model=chat_model,
        )
        answer_subgraph = build_answer_subgraph(
            settings=settings, chat_model=chat_model
        )
        graph.add_node(
            "preprocess_subgraph",
            _wrap_node_with_io("preprocess_subgraph", preprocess_subgraph),
            metadata=node_metadata("preprocess_subgraph", side_effect_type="subgraph"),
        )
        graph.add_node(
            "retrieval_subgraph",
            _wrap_node_with_io("retrieval_subgraph", retrieval_subgraph),
            metadata=node_metadata("retrieval_subgraph", side_effect_type="subgraph"),
        )
        graph.add_node(
            "answer_subgraph",
            _wrap_node_with_io("answer_subgraph", answer_subgraph),
            metadata=node_metadata("answer_subgraph", side_effect_type="subgraph"),
        )
        graph.add_node(
            "transform_query",
            _wrap_node_with_io(
                "transform_query", partial(transform_query_for_retry, settings=settings)
            ),
            metadata=node_metadata(
                "transform_query",
                side_effect_type="llm",
                retry_policy=transform_retry_policy,
            ),
            retry_policy=transform_retry_policy,
        )
        graph.add_node(
            "force_exit",
            _wrap_node_with_io(
                "force_exit", partial(force_exit_node, settings=settings)
            ),
            metadata=node_metadata("force_exit", side_effect_type="deterministic_rule"),
        )
        graph.set_entry_point("preprocess_subgraph")
        graph.add_conditional_edges(
            "preprocess_subgraph",
            _route_after_preprocess_subgraph,
            {
                "retrieval_subgraph": "retrieval_subgraph",
                "transform_query": "transform_query",
                "force_exit": "force_exit",
            },
        )
        graph.add_edge("retrieval_subgraph", "answer_subgraph")
        graph.add_edge("transform_query", "retrieval_subgraph")
        graph.add_conditional_edges(
            "answer_subgraph",
            lambda s: route_after_answer_review(s, settings),
            {
                "END": END,
                "transform_query": "transform_query",
                "force_exit": "force_exit",
            },
        )
        graph.add_edge("force_exit", END)
        self._graph_builder = graph

    def compile(
        self,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
    ):
        return self._graph_builder.compile(
            checkpointer=checkpointer,
            store=store,
        )

    def make_run_config(self, thread_id: str | None = None) -> dict[str, Any]:
        return build_kb_chat_run_config(
            thread_id=thread_id,
            recursion_limit=int(self._settings.kb_chat_graph_recursion_limit),
        )

    def make_run_context(
        self,
        *,
        thread_id: str | None = None,
        state: dict[str, Any] | None = None,
        user_id: str | None = None,
        kb_ids: list[str] | None = None,
        runtime_config: dict[str, Any] | None = None,
    ) -> KbChatGraphContext:
        return build_kb_chat_run_context(
            thread_id=thread_id,
            state=state,
            user_id=user_id,
            kb_ids=kb_ids,
            runtime_config=runtime_config,
            settings=self._settings,
        )

    async def run(
        self,
        state: dict,
        thread_id: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
        run_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        compiled = self.compile(checkpointer=checkpointer, store=store)
        config = self.make_run_config(thread_id=thread_id)
        context = run_context or self.make_run_context(thread_id=thread_id, state=state)
        result = await compiled.ainvoke(
            build_graph_input_state(state),
            config,
            context=context,
        )
        return cast(dict[str, Any], result)

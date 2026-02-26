"""KB Chat agentic LangGraph (preprocess -> retrieval -> reflection -> answer)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict, cast
import hashlib
import inspect
import json

from functools import partial

from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.cache.memory import InMemoryCache
from langgraph.config import get_stream_writer
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import CachePolicy, Command, RetryPolicy

from app.agents.kb_chat_agentic_state import KbChatAgenticState
from app.agents.tool_calling.registry import ToolMeta
from app.core.settings import get_settings

from app.agents.kb_chat_agentic.preprocess import (
    ambiguity_check,
    complexity_router,
    decomposition,
    entity_expand,
    generate_variants,
    hyde,
    merge_context,
    normalize_rewrite,
    prepare_messages,
    coref_rewrite,
)
from app.agents.kb_chat_agentic.tool_loop import force_exit_node
from app.agents.kb_chat_agentic.reflection import (
    answer_review,
    dispatch_subqueries,
    doc_grader,
    finalize_answer,
    generate_draft,
    kb_retrieve_context,
    merge_subquery_context,
    retrieve_subquery_context,
    route_after_answer_review,
    route_after_doc_grader,
    transform_query_for_retry,
)


_NODE_METADATA: dict[str, dict[str, Any]] = {
    "merge_context": {"label": "\u4e0a\u4e0b\u6587\u5408\u5e76", "phase": "preprocess", "order": 0},
    "coref_rewrite": {"label": "\u6307\u4ee3\u6d88\u89e3", "phase": "preprocess", "order": 1},
    "ambiguity_check": {"label": "\u6b67\u4e49\u5224\u65ad", "phase": "preprocess", "order": 2},
    "normalize_rewrite": {"label": "\u95ee\u9898\u89c4\u8303", "phase": "preprocess", "order": 3},
    "complexity_router": {"label": "\u590d\u6742\u5ea6\u8def\u7531", "phase": "preprocess", "order": 4},
    "decomposition": {"label": "\u95ee\u9898\u5206\u89e3", "phase": "preprocess", "order": 5},
    "generate_variants": {"label": "\u591a\u8def\u6269\u5c55", "phase": "preprocess", "order": 6},
    "entity_expand": {"label": "\u5b9e\u4f53\u6269\u5c55", "phase": "preprocess", "order": 7},
    "hyde": {"label": "HyDE\u6269\u5c55", "phase": "preprocess", "order": 8},
    "prepare_messages": {"label": "\u6d88\u606f\u6574\u7406", "phase": "preprocess", "order": 9},
    "dispatch_subqueries": {"label": "\u5b50\u67e5\u8be2\u6d3e\u53d1", "phase": "retrieve", "order": 10},
    "retrieve_subquery": {"label": "\u5b50\u67e5\u8be2\u68c0\u7d22", "phase": "retrieve", "order": 11},
    "merge_subquery_context": {"label": "\u5b50\u67e5\u8be2\u4e0a\u4e0b\u6587\u5408\u5e76", "phase": "retrieve", "order": 12},
    "retrieve": {"label": "\u77e5\u8bc6\u68c0\u7d22", "phase": "retrieve", "order": 13},
    "doc_grader": {"label": "\u6587\u6863\u5224\u5b9a", "phase": "judge", "order": 14},
    "transform_query": {"label": "\u67e5\u8be2\u6539\u5199", "phase": "retrieve", "order": 15},
    "generate": {"label": "\u7b54\u6848\u751f\u6210", "phase": "generate", "order": 16},
    "answer_review": {"label": "\u7b54\u6848\u5ba1\u67e5", "phase": "verify", "order": 17},
    "finalize": {"label": "\u7b54\u6848\u6574\u7406", "phase": "finalize", "order": 18},
    "force_exit": {"label": "\u63d0\u524d\u7ec8\u6b62", "phase": "finalize", "order": 19},
}

_KB_CHAT_GRAPH_CACHE = InMemoryCache()


class KbChatGraphContext(TypedDict, total=False):
    """Run-scoped immutable context passed via LangGraph context_schema."""

    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


class PrepareMessagesInput(TypedDict, total=False):
    """Narrowed input schema for prepare_messages node."""

    user_input: str
    coref_query: str
    normalized_query: str
    normalized_meta: dict[str, Any]
    query_strategy: str
    decomposition_plan: dict[str, Any]
    sub_queries: list[str]
    multi_queries: list[str]
    hyde_docs: list[str]
    query_items: list[dict[str, Any]]
    stage_summaries: dict[str, Any]
    runtime_config: dict[str, Any]
    reflection: dict[str, Any]


def _resolve_flag(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key)
    return value if isinstance(value, bool) else default


def _resolve_topology_config(
    *,
    settings: Any,
    kb_chat_config: dict[str, Any] | None,
) -> tuple[bool, bool]:
    raw = kb_chat_config if isinstance(kb_chat_config, dict) else {}
    ambiguity = _resolve_flag(
        raw,
        "ambiguity_check_enabled",
        bool(settings.kb_chat_ambiguity_check_enabled),
    )
    hyde_flag = _resolve_flag(
        raw,
        "hyde_enabled",
        bool(settings.kb_chat_hyde_enabled),
    )
    return ambiguity, hyde_flag


def _complexity_cache_key_factory(*, direct_target: str) -> Any:
    def _key_func(*args: Any, **kwargs: Any) -> str:
        state: dict[str, Any] = {}
        if args and isinstance(args[0], dict):
            state = args[0]
        elif isinstance(kwargs.get("state"), dict):
            state = cast(dict[str, Any], kwargs["state"])
        stage_summaries = state.get("stage_summaries")
        stage_fingerprint = "none"
        if isinstance(stage_summaries, dict):
            try:
                stage_payload = json.dumps(
                    stage_summaries,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=_json_default,
                )
                stage_fingerprint = hashlib.sha256(
                    stage_payload.encode("utf-8")
                ).hexdigest()
            except Exception:
                stage_fingerprint = "serialize_error"
        normalized_meta = state.get("normalized_meta")
        if not isinstance(normalized_meta, dict):
            normalized_meta = {}
        query = state.get("normalized_query")
        if not isinstance(query, str) or not query.strip():
            fallback_query = state.get("user_input")
            query = fallback_query if isinstance(fallback_query, str) else ""
        payload = {
            "router_version": "kb_chat_complexity_router_v4",
            "query": query.strip(),
            "recall_risk": str(normalized_meta.get("recall_risk") or "unknown"),
            "has_multi_target": bool(normalized_meta.get("has_multi_target")),
            "is_comparison": bool(normalized_meta.get("is_comparison")),
            "direct_target": direct_target,
            "stage_fingerprint": stage_fingerprint,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    return _key_func


def _entity_expand_cache_key_factory() -> Any:
    def _key_func(*args: Any, **kwargs: Any) -> str:
        state: dict[str, Any] = {}
        if args and isinstance(args[0], dict):
            state = args[0]
        elif isinstance(kwargs.get("state"), dict):
            state = cast(dict[str, Any], kwargs["state"])
        normalized_query = state.get("normalized_query")
        if not isinstance(normalized_query, str):
            normalized_query = ""
        multi_queries = state.get("multi_queries")
        if not isinstance(multi_queries, list):
            multi_queries = []
        normalized_meta = state.get("normalized_meta")
        if not isinstance(normalized_meta, dict):
            normalized_meta = {}
        payload = {
            "version": "kb_chat_entity_expand_v1",
            "normalized_query": normalized_query.strip(),
            "multi_queries": [
                str(item).strip()
                for item in multi_queries
                if isinstance(item, str) and str(item).strip()
            ],
            "aliases": [
                str(item).strip()
                for item in (normalized_meta.get("aliases") or [])
                if isinstance(item, str) and str(item).strip()
            ],
            "entities": [
                str(item).strip()
                for item in (normalized_meta.get("entities") or [])
                if isinstance(item, str) and str(item).strip()
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    return _key_func


def _prepare_messages_cache_key_factory() -> Any:
    def _key_func(*args: Any, **kwargs: Any) -> str:
        state: dict[str, Any] = {}
        if args and isinstance(args[0], dict):
            state = args[0]
        elif isinstance(kwargs.get("state"), dict):
            state = cast(dict[str, Any], kwargs["state"])

        decomposition_plan = state.get("decomposition_plan")
        if not isinstance(decomposition_plan, dict):
            decomposition_plan = {}
        payload = {
            "version": "kb_chat_prepare_messages_v1",
            "strategy": str(state.get("query_strategy") or "direct"),
            "normalized_query": str(state.get("normalized_query") or "").strip(),
            "sub_queries": [
                str(item).strip()
                for item in (state.get("sub_queries") or [])
                if isinstance(item, str) and str(item).strip()
            ],
            "multi_queries": [
                str(item).strip()
                for item in (state.get("multi_queries") or [])
                if isinstance(item, str) and str(item).strip()
            ],
            "hyde_docs": [
                str(item).strip()
                for item in (state.get("hyde_docs") or [])
                if isinstance(item, str) and str(item).strip()
            ],
            "sub_query_specs": decomposition_plan.get("sub_query_specs")
            if isinstance(decomposition_plan.get("sub_query_specs"), list)
            else [],
            "runtime_config": state.get("runtime_config")
            if isinstance(state.get("runtime_config"), dict)
            else {},
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default)

    return _key_func


def build_kb_chat_run_config(*, thread_id: str | None, recursion_limit: int) -> dict[str, Any]:
    """Build LangGraph invocation config for KB chat.

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
    settings: Any,
) -> KbChatGraphContext:
    """Build run context for context_schema-backed node runtime data."""

    state_obj = state if isinstance(state, dict) else {}
    memory_keys = state_obj.get("memory_keys")
    if not isinstance(memory_keys, dict):
        memory_keys = {}
    runtime_config = state_obj.get("runtime_config")
    if not isinstance(runtime_config, dict):
        runtime_config = {}
    kb_ids = memory_keys.get("kb_ids")
    if not isinstance(kb_ids, list):
        kb_ids = []
    return {
        "thread_id": str(thread_id or memory_keys.get("thread_id") or ""),
        "user_id": str(memory_keys.get("user_id") or "local"),
        "kb_ids": [str(item) for item in kb_ids if isinstance(item, str) and item.strip()],
        "runtime_config": runtime_config,
        "message_budget": {
            "max_candidates": int(
                runtime_config.get("parallel_retrieval_max_branches")
                if isinstance(runtime_config.get("parallel_retrieval_max_branches"), int)
                else getattr(settings, "kb_chat_parallel_retrieval_max_branches", 6)
            ),
            "min_queries": int(
                runtime_config.get("parallel_retrieval_min_queries")
                if isinstance(runtime_config.get("parallel_retrieval_min_queries"), int)
                else getattr(settings, "kb_chat_parallel_retrieval_min_queries", 2)
            ),
            "include_main": bool(
                runtime_config.get("parallel_retrieval_include_main")
                if isinstance(runtime_config.get("parallel_retrieval_include_main"), bool)
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
        role = "用户" if role_raw == "user" else "助手" if role_raw == "assistant" else role_raw
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
        "generate": "generator",
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
    elif node_name == "coref_rewrite":
        _append_display_item(
            items,
            key="query",
            label="输入问题",
            value=_pick_text(snapshot, "rewrite_input_query", "user_input"),
        )
    elif node_name in {"ambiguity_check", "normalize_rewrite"}:
        _append_display_item(
            items,
            key="query",
            label="输入问题",
            value=_pick_text(
                snapshot,
                "coref_query",
                "rewrite_input_query",
                "user_input",
            ),
        )
    elif node_name in {
        "complexity_router",
        "decomposition",
        "generate_variants",
        "entity_expand",
        "hyde",
    }:
        _append_display_item(
            items,
            key="normalized_query",
            label="规范化问题",
            value=_pick_text(snapshot, "normalized_query", "coref_query", "user_input"),
        )
        if node_name == "entity_expand":
            _append_display_item(
                items,
                key="multi_queries",
                label="待扩展查询",
                value=_pick_string_list(snapshot, "multi_queries"),
            )
    elif node_name == "prepare_messages":
        _append_display_item(
            items,
            key="normalized_query",
            label="主问题",
            value=_pick_text(snapshot, "normalized_query", "coref_query", "user_input"),
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
        _append_display_item(
            items,
            key="subquery_runs_count",
            label="分支结果数",
            value=len(snapshot.get("subquery_runs"))
            if isinstance(snapshot.get("subquery_runs"), list)
            else None,
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
                value=_pick_text(snapshot, "normalized_query", "coref_query", "user_input"),
            )
    elif node_name == "doc_grader":
        _append_display_item(
            items,
            key="question",
            label="待判定问题",
            value=_pick_text(snapshot, "merged_context", "user_input"),
        )
    elif node_name == "transform_query":
        _append_display_item(
            items,
            key="normalized_query",
            label="当前问题",
            value=_pick_text(snapshot, "normalized_query", "coref_query", "user_input"),
        )
        _append_display_item(
            items,
            key="reason",
            label="改写原因",
            value=reflection.get("reason"),
        )
    elif node_name == "generate":
        _append_display_item(
            items,
            key="question",
            label="待回答问题",
            value=_pick_text(snapshot, "merged_context", "user_input"),
        )
    elif node_name == "answer_review":
        _append_display_item(
            items,
            key="question",
            label="用户问题",
            value=_pick_text(snapshot, "merged_context", "user_input"),
        )
        _append_display_item(
            items,
            key="draft_answer",
            label="待评估答案",
            value=_pick_text(snapshot, "draft_answer"),
        )
    elif node_name == "finalize":
        _append_display_item(
            items,
            key="draft_answer",
            label="答案草稿",
            value=_pick_text(snapshot, "draft_answer", "final_answer"),
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
            value=_pick_text(snapshot, "display_context", "merged_context"),
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
    elif node_name == "coref_rewrite":
        _append_display_item(
            items,
            key="coref_query",
            label="改写后问题",
            value=_pick_text(snapshot, "coref_query"),
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
    elif node_name == "normalize_rewrite":
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
    elif node_name == "complexity_router":
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
            key="goto",
            label="下一节点",
            value=summary.get("goto"),
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
    elif node_name == "entity_expand":
        multi_queries = _pick_string_list(snapshot, "multi_queries")
        _append_display_item(
            items,
            key="multi_queries",
            label="澶氳矾鏌ヨ",
            value=multi_queries,
        )
        _append_display_item(
            items,
            key="input_count",
            label="杈撳叆鏁伴噺",
            value=summary.get("input_count"),
        )
        _append_display_item(
            items,
            key="expanded_count",
            label="鎵╁睍鍚庢暟閲?",
            value=summary.get("expanded_count"),
        )
        _append_display_item(
            items,
            key="added_count",
            label="鏂板鏁伴噺",
            value=summary.get("added_count"),
        )
        _append_display_item(
            items,
            key="pruned_count",
            label="鍓灊鏁伴噺",
            value=summary.get("pruned_count"),
        )
        _append_display_item(
            items,
            key="min_confidence",
            label="鏈€浣庣疆淇″害",
            value=summary.get("min_confidence"),
        )
        _append_display_item(
            items,
            key="drift_guardrail_triggered",
            label="鏄惁鍛戒腑婕傜Щ闃插",
            value=summary.get("drift_guardrail_triggered"),
        )
        _append_display_item(
            items,
            key="fallback_reason",
            label="闄嶇骇鍘熷洜",
            value=summary.get("fallback_reason"),
        )
        _append_display_item(
            items,
            key="reason",
            label="澶勭悊鍘熷洜",
            value=summary.get("reason"),
        )
    elif node_name == "hyde":
        _append_display_item(
            items,
            key="enabled",
            label="是否启用 HyDE",
            value=summary.get("enabled"),
        )
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
    elif node_name == "prepare_messages":
        message_plan = _as_dict(summary.get("message_plan")) or {}
        query_bundle_summary = _as_dict(summary.get("query_bundle")) or {}
        diagnostics = _as_dict(summary.get("diagnostics")) or {}
        budget = _as_dict(message_plan.get("budget")) or {}
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
            value=query_bundle_summary.get("items_count")
            if query_bundle_summary.get("items_count") is not None
            else len(query_items),
        )
        _append_display_item(
            items,
            key="message_plan_candidate_count",
            label="候选查询数",
            value=message_plan.get("candidate_count"),
        )
        _append_display_item(
            items,
            key="message_plan_dropped_count",
            label="丢弃查询数",
            value=message_plan.get("dropped_count"),
        )
        _append_display_item(
            items,
            key="message_plan_strategy",
            label="消息策略",
            value=message_plan.get("strategy"),
        )
        _append_display_item(
            items,
            key="message_plan_max_candidates",
            label="分支预算上限",
            value=budget.get("max_candidates"),
        )
        _append_display_item(
            items,
            key="fallback_reason",
            label="回退原因",
            value=diagnostics.get("fallback_reason"),
        )
        _append_display_item(
            items,
            key="quality_signals",
            label="质量信号",
            value=diagnostics.get("quality_signals"),
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
    elif node_name == "retrieve_subquery":
        runs = snapshot.get("subquery_runs")
        first = runs[0] if isinstance(runs, list) and runs else {}
        run = first if isinstance(first, dict) else {}
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
    elif node_name == "doc_grader":
        _append_display_item(
            items,
            key="passed",
            label="相关性是否通过",
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
    elif node_name == "generate":
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
    elif node_name == "answer_review":
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
    elif node_name == "finalize":
        _append_display_item(
            items,
            key="final_answer",
            label="最终答案",
            value=_pick_text(snapshot, "final_answer"),
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
    signature = inspect.signature(node_callable)
    accepts_runtime = "runtime" in signature.parameters

    async def _wrapped(
        state: dict[str, Any], runtime: Runtime[Any]
    ) -> dict[str, Any] | Command[str]:
        writer = None
        try:
            writer = get_stream_writer()
        except Exception:
            writer = None

        input_snapshot = _to_json_compatible(state)
        input_summary = _build_snapshot_summary(input_snapshot)
        display_input_items = _build_node_input_display_items(
            node_name=node_name,
            input_snapshot=input_snapshot,
        )
        started_at = datetime.now(timezone.utc)

        if callable(writer):
            payload = {
                "event_type": "node_io",
                "node_name": node_name,
                "phase": "start",
                "input_summary": input_summary,
                "input_snapshot": input_snapshot,
                "ts": _to_iso_now(),
            }
            if display_input_items:
                payload["display_input_items"] = display_input_items
            writer(
                payload
            )

        try:
            result = (
                node_callable(state, runtime=runtime)
                if accepts_runtime
                else node_callable(state)
            )
            updates = await result if inspect.isawaitable(result) else result
            if isinstance(updates, Command):
                command_update = updates.update
                if isinstance(command_update, dict):
                    output_payload = {**command_update}
                elif command_update is None:
                    output_payload = {}
                else:
                    output_payload = {"value": _to_json_compatible(command_update)}
                output_payload["__command__"] = {
                    "goto": _to_json_compatible(updates.goto),
                    "resume": _to_json_compatible(updates.resume),
                    "graph": _to_json_compatible(updates.graph),
                }
                output_snapshot = _to_json_compatible(output_payload)
                result_payload: dict[str, Any] | Command[str] = updates
            else:
                safe_updates = (
                    updates
                    if isinstance(updates, dict)
                    else {"value": _to_json_compatible(updates)}
                )
                output_snapshot = _to_json_compatible(safe_updates)
                result_payload = safe_updates
            output_summary = _build_snapshot_summary(output_snapshot)
            display_output_items = _build_node_output_display_items(
                node_name=node_name,
                output_snapshot=output_snapshot,
            )
            if callable(writer):
                payload = {
                    "event_type": "node_io",
                    "node_name": node_name,
                    "phase": "end",
                    "input_summary": input_summary,
                    "output_summary": output_summary,
                    "output_snapshot": output_snapshot,
                    "latency_ms": max(
                        0,
                        int(
                            (datetime.now(timezone.utc) - started_at).total_seconds()
                            * 1000
                        ),
                    ),
                    "ts": _to_iso_now(),
                }
                if display_input_items:
                    payload["display_input_items"] = display_input_items
                if display_output_items:
                    payload["display_output_items"] = display_output_items
                writer(
                    payload
                )
            return result_payload
        except Exception as exc:
            if callable(writer):
                display_output_items = _build_node_output_display_items(
                    node_name=node_name,
                    output_snapshot=None,
                    error_summary=str(exc),
                )
                payload = {
                    "event_type": "node_io",
                    "node_name": node_name,
                    "phase": "error",
                    "input_summary": input_summary,
                    "error_summary": str(exc),
                    "latency_ms": max(
                        0,
                        int(
                            (datetime.now(timezone.utc) - started_at).total_seconds()
                            * 1000
                        ),
                    ),
                    "ts": _to_iso_now(),
                }
                if display_input_items:
                    payload["display_input_items"] = display_input_items
                if display_output_items:
                    payload["display_output_items"] = display_output_items
                writer(
                    payload
                )
            raise

    return _wrapped


class KbChatAgenticGraph:
    """Agentic KB chat graph (preprocess → retrieval → reflection → answer)."""

    def __init__(
        self,
        *,
        chat_model: ChatOpenAI,
        tools: list[BaseTool],
        tool_meta_by_name: dict[str, ToolMeta],  # kept for signature compatibility
        kb_chat_config: dict[str, Any] | None = None,
    ) -> None:
        del tool_meta_by_name  # not used in this stage (no human review)
        settings = get_settings()
        self._settings = settings
        (ambiguity_enabled, hyde_enabled) = _resolve_topology_config(
            settings=settings,
            kb_chat_config=kb_chat_config,
        )
        llm_preprocess_retry_policy = RetryPolicy(max_attempts=2)
        direct_target = "hyde" if hyde_enabled else "prepare_messages"
        complexity_cache_enabled = bool(
            getattr(settings, "kb_chat_complexity_cache_enabled", True)
        )
        complexity_cache_ttl = int(
            getattr(settings, "kb_chat_complexity_cache_ttl_seconds", 120)
        )
        complexity_cache_policy = (
            CachePolicy(
                key_func=_complexity_cache_key_factory(direct_target=direct_target),
                ttl=complexity_cache_ttl,
            )
            if complexity_cache_enabled and complexity_cache_ttl > 0
            else None
        )
        entity_expand_cache_policy = (
            CachePolicy(
                key_func=_entity_expand_cache_key_factory(),
                ttl=complexity_cache_ttl,
            )
            if complexity_cache_enabled and complexity_cache_ttl > 0
            else None
        )
        prepare_messages_cache_policy = (
            CachePolicy(
                key_func=_prepare_messages_cache_key_factory(),
                ttl=complexity_cache_ttl,
            )
            if complexity_cache_enabled and complexity_cache_ttl > 0
            else None
        )
        self._graph_cache = (
            _KB_CHAT_GRAPH_CACHE
            if (
                complexity_cache_policy
                or entity_expand_cache_policy
                or prepare_messages_cache_policy
            )
            else None
        )

        graph = StateGraph(
            state_schema=KbChatAgenticState,
            context_schema=KbChatGraphContext,
        )

        # -----------------
        # Preprocess chain
        # -----------------
        graph.add_node(
            "merge_context",
            _wrap_node_with_io("merge_context", partial(merge_context, settings=settings)),
            metadata=_NODE_METADATA["merge_context"],
        )
        graph.add_node(
            "coref_rewrite",
            _wrap_node_with_io("coref_rewrite", partial(coref_rewrite, settings=settings)),
            metadata=_NODE_METADATA["coref_rewrite"],
        )
        if ambiguity_enabled:
            graph.add_node(
                "ambiguity_check",
                _wrap_node_with_io(
                    "ambiguity_check", partial(ambiguity_check, settings=settings)
                ),
                metadata=_NODE_METADATA["ambiguity_check"],
            )
        graph.add_node(
            "normalize_rewrite",
            _wrap_node_with_io(
                "normalize_rewrite", partial(normalize_rewrite, settings=settings)
            ),
            metadata=_NODE_METADATA["normalize_rewrite"],
        )
        graph.add_node(
            "complexity_router",
            _wrap_node_with_io(
                "complexity_router", partial(complexity_router, settings=settings)
            ),
            metadata=_NODE_METADATA["complexity_router"],
            retry_policy=llm_preprocess_retry_policy,
            cache_policy=complexity_cache_policy,
            destinations=(
                "decomposition",
                "generate_variants",
                direct_target,
            ),
        )
        graph.add_node(
            "decomposition",
            _wrap_node_with_io(
                "decomposition", partial(decomposition, settings=settings)
            ),
            metadata=_NODE_METADATA["decomposition"],
            retry_policy=llm_preprocess_retry_policy,
        )
        graph.add_node(
            "generate_variants",
            _wrap_node_with_io(
                "generate_variants", partial(generate_variants, settings=settings)
            ),
            metadata=_NODE_METADATA["generate_variants"],
            retry_policy=llm_preprocess_retry_policy,
        )
        graph.add_node(
            "entity_expand",
            _wrap_node_with_io(
                "entity_expand", partial(entity_expand, settings=settings)
            ),
            metadata=_NODE_METADATA["entity_expand"],
            retry_policy=llm_preprocess_retry_policy,
            cache_policy=entity_expand_cache_policy,
            destinations=("hyde", "prepare_messages")
            if hyde_enabled
            else ("prepare_messages",),
        )
        if hyde_enabled:
            graph.add_node(
                "hyde",
                _wrap_node_with_io("hyde", partial(hyde, settings=settings)),
                metadata=_NODE_METADATA["hyde"],
                retry_policy=llm_preprocess_retry_policy,
            )
        graph.add_node(
            "prepare_messages",
            _wrap_node_with_io(
                "prepare_messages", partial(prepare_messages, settings=settings)
            ),
            metadata=_NODE_METADATA["prepare_messages"],
            input_schema=PrepareMessagesInput,
            retry_policy=llm_preprocess_retry_policy,
            cache_policy=prepare_messages_cache_policy,
            destinations=("dispatch_subqueries", "transform_query"),
        )
        graph.add_node(
            "dispatch_subqueries",
            _wrap_node_with_io(
                "dispatch_subqueries",
                partial(dispatch_subqueries, settings=settings),
            ),
            metadata=_NODE_METADATA["dispatch_subqueries"],
            destinations=("retrieve_subquery", "retrieve"),
        )

        # -----------------
        # Retrieval/Reflection
        # -----------------
        kb_tool = next((t for t in tools if getattr(t, "name", None) == "kb_retrieve"), None)
        if kb_tool is None:
            raise RuntimeError("kb_retrieve tool is required for agentic KB chat")

        graph.add_node(
            "retrieve_subquery",
            _wrap_node_with_io(
                "retrieve_subquery",
                partial(retrieve_subquery_context, settings=settings, kb_tool=kb_tool),
            ),
            metadata=_NODE_METADATA["retrieve_subquery"],
        )
        graph.add_node(
            "merge_subquery_context",
            _wrap_node_with_io(
                "merge_subquery_context",
                partial(merge_subquery_context, settings=settings),
            ),
            metadata=_NODE_METADATA["merge_subquery_context"],
        )
        graph.add_node(
            "retrieve",
            _wrap_node_with_io(
                "retrieve", partial(kb_retrieve_context, settings=settings, kb_tool=kb_tool)
            ),
            metadata=_NODE_METADATA["retrieve"],
        )
        graph.add_node(
            "doc_grader",
            _wrap_node_with_io(
                "doc_grader", partial(doc_grader, settings=settings, chat_model=chat_model)
            ),
            metadata=_NODE_METADATA["doc_grader"],
        )
        graph.add_node(
            "transform_query",
            _wrap_node_with_io(
                "transform_query", partial(transform_query_for_retry, settings=settings)
            ),
            metadata=_NODE_METADATA["transform_query"],
        )
        graph.add_node(
            "generate",
            _wrap_node_with_io(
                "generate",
                partial(generate_draft, settings=settings, chat_model=chat_model),
            ),
            metadata=_NODE_METADATA["generate"],
        )
        graph.add_node(
            "answer_review",
            _wrap_node_with_io(
                "answer_review",
                partial(answer_review, settings=settings, chat_model=chat_model),
            ),
            metadata=_NODE_METADATA["answer_review"],
        )
        graph.add_node(
            "finalize",
            _wrap_node_with_io("finalize", finalize_answer),
            metadata=_NODE_METADATA["finalize"],
        )
        graph.add_node(
            "force_exit",
            _wrap_node_with_io(
                "force_exit", partial(force_exit_node, settings=settings)
            ),
            metadata=_NODE_METADATA["force_exit"],
        )

        # Entry
        graph.set_entry_point("merge_context")
        graph.add_edge("merge_context", "coref_rewrite")

        if ambiguity_enabled:
            graph.add_edge("coref_rewrite", "ambiguity_check")

            # Ambiguity routing (clarify => ForceExit)
            def _route_after_ambiguity(state: dict) -> str:
                reflection = state.get("reflection")
                action = reflection.get("action") if isinstance(reflection, dict) else None
                return "force_exit" if action == "clarify" else "normalize_rewrite"

            graph.add_conditional_edges(
                "ambiguity_check",
                _route_after_ambiguity,
                {"force_exit": "force_exit", "normalize_rewrite": "normalize_rewrite"},
            )
        else:
            graph.add_edge("coref_rewrite", "normalize_rewrite")

        graph.add_edge("normalize_rewrite", "complexity_router")
        graph.add_edge("generate_variants", "entity_expand")

        if hyde_enabled:
            graph.add_edge("decomposition", "hyde")
            graph.add_edge("entity_expand", "hyde")
            graph.add_edge("hyde", "prepare_messages")
        else:
            graph.add_edge("decomposition", "prepare_messages")
            graph.add_edge("entity_expand", "prepare_messages")

        graph.add_edge("prepare_messages", "dispatch_subqueries")
        graph.add_edge("retrieve_subquery", "merge_subquery_context")
        graph.add_edge("merge_subquery_context", "doc_grader")
        graph.add_edge("retrieve", "doc_grader")

        # Doc relevance → Generate or TransformQuery
        graph.add_conditional_edges(
            "doc_grader",
            lambda s: route_after_doc_grader(s, settings),
            {"generate": "generate", "transform_query": "transform_query", "force_exit": "force_exit"},
        )

        graph.add_edge("transform_query", "retrieve")

        # Draft generation → AnswerReview → Finalize/TransformQuery
        graph.add_edge("generate", "answer_review")
        graph.add_conditional_edges(
            "answer_review",
            lambda s: route_after_answer_review(s, settings),
            {
                "finalize": "finalize",
                "transform_query": "transform_query",
                "force_exit": "force_exit",
            },
        )

        graph.add_edge("finalize", END)
        graph.add_edge("force_exit", END)

        self._graph_builder = graph

    def compile(
        self,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
    ):
        return self._graph_builder.compile(
            checkpointer=checkpointer,
            cache=self._graph_cache,
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
    ) -> KbChatGraphContext:
        return build_kb_chat_run_context(
            thread_id=thread_id,
            state=state,
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
        result = await compiled.ainvoke(state, config, context=context)
        return cast(dict[str, Any], result)

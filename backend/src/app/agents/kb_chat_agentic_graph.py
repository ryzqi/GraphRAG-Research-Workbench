"""KB Chat agentic LangGraph (preprocess → retrieval → reflection → answer).

This graph follows the OpenSpec change `refactor-kb-agent-orchestration`:
- Preprocess: MergeContext → Coref → Ambiguity → Normalize → (Decomp|MultiQuery) → HyDE
- RetrievalLayer: run kb_retrieve once per round (Top-N context)
- ReflectionLayer: doc relevance → generation → answer review (with retrieval rewrites)

Notes:
- To keep streaming/service plumbing compatible, only the final answer is emitted as an AIMessage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
import inspect
import json

from functools import partial

from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.config import get_stream_writer
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import RetryPolicy

from app.agents.kb_chat_agentic_state import KbChatAgenticState
from app.agents.tool_calling.registry import ToolMeta
from app.core.settings import get_settings

from app.agents.kb_chat_agentic.preprocess import (
    ambiguity_check,
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
    doc_grader,
    finalize_answer,
    generate_draft,
    kb_retrieve_context,
    route_after_answer_review,
    route_after_doc_grader,
    transform_query_for_retry,
)


_NODE_METADATA: dict[str, dict[str, Any]] = {
    "merge_context": {"label": "上下文合并", "phase": "preprocess", "order": 0},
    "coref_rewrite": {"label": "指代消解", "phase": "preprocess", "order": 1},
    "ambiguity_check": {"label": "歧义判断", "phase": "preprocess", "order": 2},
    "normalize_rewrite": {"label": "问题规范化", "phase": "preprocess", "order": 3},
    "decomposition": {"label": "问题分解", "phase": "preprocess", "order": 4},
    "multi_query_check": {"label": "多路查询判断", "phase": "preprocess", "order": 5},
    "generate_variants": {"label": "多路查询扩展", "phase": "preprocess", "order": 6},
    "entity_expand": {"label": "实体扩展", "phase": "preprocess", "order": 7},
    "hyde_check": {"label": "HyDE 判断", "phase": "preprocess", "order": 8},
    "hyde": {"label": "HyDE 扩展", "phase": "preprocess", "order": 9},
    "prepare_messages": {"label": "构建查询消息", "phase": "preprocess", "order": 10},
    "retrieve": {"label": "知识检索", "phase": "retrieve", "order": 11},
    "doc_grader": {"label": "文档相关性判断", "phase": "judge", "order": 12},
    "transform_query": {"label": "查询改写重试", "phase": "retrieve", "order": 13},
    "generate": {"label": "答案生成", "phase": "generate", "order": 14},
    "answer_review": {"label": "答案审查", "phase": "verify", "order": 15},
    "finalize": {"label": "答案整理", "phase": "finalize", "order": 16},
    "force_exit": {"label": "提前终止", "phase": "finalize", "order": 17},
}


def _resolve_flag(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key)
    return value if isinstance(value, bool) else default


def _resolve_topology_config(
    *,
    settings: Any,
    kb_chat_config: dict[str, Any] | None,
) -> tuple[bool, bool, bool, bool]:
    raw = kb_chat_config if isinstance(kb_chat_config, dict) else {}
    ambiguity = _resolve_flag(
        raw,
        "ambiguity_check_enabled",
        bool(settings.kb_chat_ambiguity_check_enabled),
    )
    decomposition_flag = _resolve_flag(
        raw,
        "decomposition_enabled",
        bool(settings.kb_chat_decomposition_enabled),
    )
    multi_query = _resolve_flag(
        raw,
        "multi_query_enabled",
        bool(settings.kb_chat_multi_query_enabled),
    )
    hyde_flag = _resolve_flag(
        raw,
        "hyde_enabled",
        bool(settings.kb_chat_hyde_enabled),
    )
    if decomposition_flag and multi_query:
        # Keep consistency with config validation: decomposition wins.
        multi_query = False
    return ambiguity, decomposition_flag, multi_query, hyde_flag


def build_kb_chat_run_config(*, thread_id: str | None, recursion_limit: int) -> dict[str, Any]:
    """Build LangGraph invocation config for KB chat.

    `recursion_limit` must stay at top-level config (not under `configurable`).
    """
    config: dict[str, Any] = {"recursion_limit": int(recursion_limit)}
    if thread_id:
        config["configurable"] = {"thread_id": thread_id}
    return config


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
    elif node_name in {"coref_rewrite", "ambiguity_check", "normalize_rewrite"}:
        _append_display_item(
            items,
            key="query",
            label="输入问题",
            value=_pick_text(snapshot, "coref_query", "merged_context", "user_input"),
        )
    elif node_name in {"decomposition", "generate_variants", "entity_expand", "hyde"}:
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
        _append_display_item(
            items,
            key="hyde_doc",
            label="HyDE 内容",
            value=_pick_text(snapshot, "hyde_doc"),
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
    elif node_name == "coref_rewrite":
        _append_display_item(
            items,
            key="coref_query",
            label="改写后问题",
            value=_pick_text(snapshot, "coref_query"),
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
    elif node_name in {"generate_variants", "entity_expand"}:
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
        _append_display_item(
            items,
            key="enabled",
            label="是否启用 HyDE",
            value=summary.get("enabled"),
        )
        _append_display_item(
            items,
            key="hyde_doc",
            label="HyDE 生成内容",
            value=_pick_text(snapshot, "hyde_doc"),
        )
        _append_display_item(
            items,
            key="reason",
            label="处理原因",
            value=summary.get("reason"),
        )
    elif node_name == "prepare_messages":
        query_items = _format_query_items(snapshot.get("query_items"))
        _append_display_item(
            items,
            key="query_items",
            label="查询项",
            value=query_items,
        )
        _append_display_item(
            items,
            key="query_items_count",
            label="查询项数量",
            value=summary.get("query_items_count")
            if summary.get("query_items_count") is not None
            else len(query_items),
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

    async def _wrapped(state: dict[str, Any], runtime: Runtime[Any]) -> dict[str, Any]:
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
            safe_updates = (
                updates
                if isinstance(updates, dict)
                else {"value": _to_json_compatible(updates)}
            )
            output_snapshot = _to_json_compatible(safe_updates)
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
            return safe_updates
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
        (
            ambiguity_enabled,
            decomposition_enabled,
            multi_query_enabled,
            hyde_enabled,
        ) = _resolve_topology_config(
            settings=settings,
            kb_chat_config=kb_chat_config,
        )
        llm_preprocess_retry_policy = RetryPolicy(max_attempts=2)

        graph = StateGraph(KbChatAgenticState)

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
        if decomposition_enabled:
            graph.add_node(
                "decomposition",
                _wrap_node_with_io(
                    "decomposition", partial(decomposition, settings=settings)
                ),
                metadata=_NODE_METADATA["decomposition"],
                retry_policy=llm_preprocess_retry_policy,
            )
        if multi_query_enabled:
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
        )

        # -----------------
        # Retrieval/Reflection
        # -----------------
        kb_tool = next((t for t in tools if getattr(t, "name", None) == "kb_retrieve"), None)
        if kb_tool is None:
            raise RuntimeError("kb_retrieve tool is required for agentic KB chat")

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
        preprocess_tail = "normalize_rewrite"

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

        if decomposition_enabled:
            graph.add_edge("normalize_rewrite", "decomposition")
            preprocess_tail = "decomposition"
        elif multi_query_enabled:
            graph.add_edge("normalize_rewrite", "generate_variants")
            graph.add_edge("generate_variants", "entity_expand")
            preprocess_tail = "entity_expand"

        if hyde_enabled:
            graph.add_edge(preprocess_tail, "hyde")
            graph.add_edge("hyde", "prepare_messages")
        else:
            graph.add_edge(preprocess_tail, "prepare_messages")

        graph.add_edge("prepare_messages", "retrieve")
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
                "generate": "generate",
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
        return self._graph_builder.compile(checkpointer=checkpointer, store=store)

    def make_run_config(self, thread_id: str | None = None) -> dict[str, Any]:
        return build_kb_chat_run_config(
            thread_id=thread_id,
            recursion_limit=int(self._settings.kb_chat_graph_recursion_limit),
        )

    async def run(
        self,
        state: dict,
        thread_id: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
    ) -> dict[str, Any]:
        compiled = self.compile(checkpointer=checkpointer, store=store)
        config = self.make_run_config(thread_id=thread_id)
        result = await compiled.ainvoke(state, config)
        return cast(dict[str, Any], result)

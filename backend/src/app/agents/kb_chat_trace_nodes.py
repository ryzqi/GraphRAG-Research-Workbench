"""Shared KB Chat node metadata and node_io wrappers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import inspect
import json
from typing import Any

from langchain_core.runnables import Runnable
from langgraph.config import get_config, get_stream_writer
from langgraph.runtime import Runtime
from langgraph.types import Command, Send

try:  # LangGraph v1.1 task ids live in configurable runtime internals.
    from langgraph._internal._constants import CONFIG_KEY_TASK_ID
except Exception:  # pragma: no cover - fallback for unexpected packaging differences.
    CONFIG_KEY_TASK_ID = "__pregel_task_id"

from app.agents.kb_chat_trace_display_contract import (
    build_node_input_display_items as _build_contract_input_display_items,
    build_node_output_display_items as _build_contract_output_display_items,
)

DisplayItemsBuilder = Callable[..., list[dict[str, Any]]]
TRACE_SNAPSHOT_CHAR_LIMIT = 512
TRACE_SNAPSHOT_ARRAY_LIMIT = 12
TRACE_SNAPSHOT_OBJECT_KEY_LIMIT = 24
TRACE_SNAPSHOT_PREVIEW_KEY_LIMIT = 16
TRACE_DEBUG_SNAPSHOT_FLAGS: tuple[str, ...] = (
    "__trace_debug__",
    "trace_debug_snapshots",
    "debug_trace_snapshots",
)
REDACTED_STREAM_VALUE = "[REDACTED]"
_SENSITIVE_SNAPSHOT_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "session",
    "session_id",
    "token",
}

KB_CHAT_NODE_METADATA: dict[str, dict[str, Any]] = {
    "preprocess_subgraph": {"label": "预处理子图", "phase": "preprocess", "order": 0},
    "merge_context": {"label": "上下文合并", "phase": "preprocess", "order": 1},
    "resolve_reference": {"label": "指代消解", "phase": "preprocess", "order": 2},
    "ambiguity_check": {"label": "歧义判断", "phase": "preprocess", "order": 3},
    "query_normalize": {"label": "问题规范", "phase": "preprocess", "order": 4},
    "complexity_classify": {"label": "复杂度分类", "phase": "route", "order": 5},
    "generate_variants_mod": {"label": "中等变体生成", "phase": "enhance", "order": 6},
    "decomposition": {"label": "问题分解", "phase": "enhance", "order": 7},
    "generate_variants": {"label": "多路扩展", "phase": "enhance", "order": 8},
    "entity_expand": {"label": "实体扩展", "phase": "enhance", "order": 9},
    "hyde": {"label": "HyDE扩展", "phase": "enhance", "order": 10},
    "prepare_messages": {"label": "查询整理", "phase": "enhance", "order": 11},
    "preprocess_exit": {"label": "预处理出口", "phase": "enhance", "order": 12},
    "retrieval_subgraph": {"label": "检索子图", "phase": "retrieve", "order": 13},
    "retrieval_plan": {"label": "检索预算规划", "phase": "retrieve", "order": 14},
    "dispatch_subqueries": {"label": "子查询派发", "phase": "retrieve", "order": 15},
    "retrieve_subquery": {"label": "子查询检索", "phase": "retrieve", "order": 16},
    "merge_subquery_context": {"label": "子查询上下文合并", "phase": "retrieve", "order": 17},
    "retrieve": {"label": "知识检索", "phase": "retrieve", "order": 18},
    "context_compress": {"label": "上下文压缩", "phase": "retrieve", "order": 19},
    "transform_query": {"label": "查询改写", "phase": "retrieve", "order": 23},
    "answer_subgraph": {"label": "答案子图", "phase": "generate", "order": 24},
    "draft_generate": {"label": "草稿生成", "phase": "generate", "order": 25},
    "answer_review_dispatch": {"label": "审查分发", "phase": "verify", "order": 26},
    "answer_review_citation": {"label": "引用覆盖审查", "phase": "verify", "order": 27},
    "answer_review_factual": {"label": "事实正确性审查", "phase": "verify", "order": 28},
    "answer_review_answerability": {"label": "可回答性审查", "phase": "verify", "order": 29},
    "answer_review_fuse": {"label": "审查结果融合", "phase": "verify", "order": 30},
    "answer_repair": {"label": "答案修复", "phase": "verify", "order": 31},
    "answer_commit": {"label": "答案提交", "phase": "generate", "order": 32},
    "force_exit": {"label": "提前终止", "phase": "finalize", "order": 33},
}

_NODE_SUMMARY_KEY_MAP: dict[str, str] = {
    "retrieve": "retrieval_layer",
    "draft_generate": "generator",
    "generate_variants_mod": "generate_variants",
    "answer_commit": "answer_subgraph",
}



def resolve_kb_chat_node_metadata(node_id: str) -> dict[str, Any]:
    metadata = KB_CHAT_NODE_METADATA.get(node_id)
    if metadata:
        return dict(metadata)
    return {"label": node_id, "phase": None, "order": None}


def extend_kb_chat_node_metadata(node_id: str, **extras: Any) -> dict[str, Any]:
    metadata = resolve_kb_chat_node_metadata(node_id)
    metadata.update(extras)
    return metadata


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


def _truncate_preview(text: str) -> str:
    if len(text) <= TRACE_SNAPSHOT_CHAR_LIMIT:
        return text
    overflow = len(text) - TRACE_SNAPSHOT_CHAR_LIMIT
    return f"{text[:TRACE_SNAPSHOT_CHAR_LIMIT]}...(truncated +{overflow} chars)"


def _sanitize_snapshot_value(value: Any, state: dict[str, bool]) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        items = list(value.items())
        if len(items) > TRACE_SNAPSHOT_OBJECT_KEY_LIMIT:
            state["truncated"] = True
            items = items[:TRACE_SNAPSHOT_OBJECT_KEY_LIMIT]
        for key, item in items:
            if not isinstance(key, str):
                continue
            if key.lower() in _SENSITIVE_SNAPSHOT_KEYS:
                state["truncated"] = True
                state["redacted"] = True
                sanitized[key] = REDACTED_STREAM_VALUE
                continue
            sanitized[key] = _sanitize_snapshot_value(item, state)
        if len(value) > len(sanitized):
            sanitized["__truncated_keys__"] = len(value) - len(sanitized)
        return sanitized
    if isinstance(value, list):
        sanitized_items = [
            _sanitize_snapshot_value(item, state)
            for item in value[:TRACE_SNAPSHOT_ARRAY_LIMIT]
        ]
        if len(value) > TRACE_SNAPSHOT_ARRAY_LIMIT:
            state["truncated"] = True
            sanitized_items.append(f"...(+{len(value) - TRACE_SNAPSHOT_ARRAY_LIMIT} items)")
        return sanitized_items
    if isinstance(value, str):
        preview = _truncate_preview(value)
        if preview != value:
            state["truncated"] = True
        return preview
    return value


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _non_empty_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _pick_text(snapshot: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        text = _non_empty_text(snapshot.get(key))
        if text:
            return text
    return None


def _pick_string_list(snapshot: dict[str, Any], *keys: str) -> list[str] | None:
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


def _get_context_frame(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    return _as_dict(snapshot.get("context_frame"))


def _pick_context_frame_text(snapshot: dict[str, Any], key: str) -> str | None:
    frame = _get_context_frame(snapshot)
    if not frame:
        return None
    return _non_empty_text(frame.get(key))


def _pick_context_frame_turns(snapshot: dict[str, Any], key: str) -> list[str] | None:
    frame = _get_context_frame(snapshot)
    raw = frame.get(key) if frame else None
    if not isinstance(raw, list):
        return None
    lines: list[str] = []
    for item in raw:
        record = _as_dict(item)
        if not record:
            continue
        role_raw = _non_empty_text(record.get("role")) or ""
        role = "用户" if role_raw == "user" else "助手" if role_raw == "assistant" else role_raw
        text = _non_empty_text(record.get("text"))
        if not text:
            continue
        lines.append(f"{role}: {text}" if role else text)
    return lines or None


def _resolve_current_subquery_run(snapshot: dict[str, Any]) -> dict[str, Any]:
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
        summary: dict[str, Any] = {
            "kind": "object",
            "keys": len(snapshot),
            "key_count": len(snapshot),
            "preview_keys": list(snapshot.keys())[:TRACE_SNAPSHOT_PREVIEW_KEY_LIMIT],
        }
        for text_key in ("user_input", "normalized_query", "draft_answer", "final_answer"):
            text = snapshot.get(text_key)
            if isinstance(text, str):
                summary[f"{text_key}_chars"] = len(text)
        return summary
    if isinstance(snapshot, list):
        return {"kind": "array", "count": len(snapshot)}
    return {"kind": type(snapshot).__name__}


def sanitize_snapshot_for_stream(
    value: Any,
    *,
    include_snapshot: bool,
) -> tuple[Any | None, dict[str, Any]]:
    json_value = _to_json_compatible(value)
    state = {"truncated": False, "redacted": False}
    sanitized = _sanitize_snapshot_value(json_value, state)
    meta = {
        "included": include_snapshot,
        "truncated": bool(state["truncated"] or state["redacted"]),
        "redacted": bool(state["redacted"]),
        "summary": _build_snapshot_summary(sanitized),
    }
    return (sanitized if include_snapshot else None), meta


def _should_include_trace_snapshot(state: Any) -> bool:
    if not isinstance(state, dict):
        return False
    return any(bool(state.get(flag)) for flag in TRACE_DEBUG_SNAPSHOT_FLAGS)


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


def _resolve_node_label_for_display(node_name: str | None) -> str | None:
    if not isinstance(node_name, str) or not node_name.strip():
        return None
    metadata = KB_CHAT_NODE_METADATA.get(node_name.strip())
    if not isinstance(metadata, dict):
        return None
    label = metadata.get("label")
    return label.strip() if isinstance(label, str) and label.strip() else None


def _build_node_input_display_items(*, node_name: str, input_snapshot: Any) -> list[dict[str, Any]]:
    return _build_contract_input_display_items(
        node_name=node_name,
        snapshot=input_snapshot,
        node_label_resolver=_resolve_node_label_for_display,
    )


def _build_node_output_display_items(
    *,
    node_name: str,
    output_snapshot: Any,
    error_summary: str | None = None,
) -> list[dict[str, Any]]:
    return _build_contract_output_display_items(
        node_name=node_name,
        snapshot=output_snapshot,
        error_summary=error_summary,
        node_label_resolver=_resolve_node_label_for_display,
    )


def _resolve_current_task_id() -> str | None:
    try:
        config = get_config()
    except Exception:
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    task_id = configurable.get(CONFIG_KEY_TASK_ID)
    return task_id if isinstance(task_id, str) and task_id else None


def _build_event_base_payload(node_name: str) -> dict[str, Any]:
    payload = {
        "event_type": "node_io",
        "node_name": node_name,
        "node_id": node_name,
    }
    task_id = _resolve_current_task_id()
    if task_id is not None:
        payload["task_id"] = task_id
        payload["execution_id"] = task_id
    return payload


def _resolve_display_builder(
    builder: DisplayItemsBuilder | None,
    fallback: DisplayItemsBuilder,
) -> DisplayItemsBuilder:
    return builder if callable(builder) else fallback


def _command_trace(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, Command):
        return None
    trace: dict[str, Any] = {}
    goto = getattr(result, "goto", None)
    if isinstance(goto, str) and goto.strip():
        trace["goto"] = goto.strip()
    if isinstance(goto, (list, tuple)):
        targets: list[str] = []
        for item in goto:
            if isinstance(item, str) and item.strip():
                targets.append(item.strip())
            elif isinstance(item, Send) and isinstance(item.node, str) and item.node.strip():
                targets.append(item.node.strip())
        if targets:
            trace["goto_targets"] = targets
    return trace or None


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

    include_snapshots = _should_include_trace_snapshot(state)
    input_snapshot = _to_json_compatible(state)
    input_summary = _build_snapshot_summary(input_snapshot)
    input_snapshot_payload, input_snapshot_meta = sanitize_snapshot_for_stream(
        input_snapshot,
        include_snapshot=include_snapshots,
    )
    display_input_items = input_builder(node_name=node_name, input_snapshot=input_snapshot)
    started_at = datetime.now(timezone.utc)

    if callable(writer):
        payload = {
            **_build_event_base_payload(node_name),
            "phase": "start",
            "snapshot_policy": "summary_first",
            "input_summary": input_summary,
            "input_snapshot_meta": input_snapshot_meta,
            "ts": _to_iso_now(),
        }
        if input_snapshot_payload is not None:
            payload["input_snapshot"] = input_snapshot_payload
        if display_input_items:
            payload["display_input_items"] = display_input_items
        writer(payload)

    try:
        maybe_result = executor()
        result = await maybe_result if inspect.isawaitable(maybe_result) else maybe_result
        merged_snapshot = _merge_result_snapshot(input_snapshot, result)
        output_summary = _build_snapshot_summary(merged_snapshot)
        output_snapshot_payload, output_snapshot_meta = sanitize_snapshot_for_stream(
            merged_snapshot,
            include_snapshot=include_snapshots,
        )
        display_output_items = output_builder(node_name=node_name, output_snapshot=merged_snapshot)
        if callable(writer):
            payload = {
                **_build_event_base_payload(node_name),
                "phase": "end",
                "snapshot_policy": "summary_first",
                "input_summary": input_summary,
                "output_summary": output_summary,
                "input_snapshot_meta": input_snapshot_meta,
                "output_snapshot_meta": output_snapshot_meta,
                "latency_ms": max(0, int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)),
                "ts": _to_iso_now(),
            }
            if input_snapshot_payload is not None:
                payload["input_snapshot"] = input_snapshot_payload
            if output_snapshot_payload is not None:
                payload["output_snapshot"] = output_snapshot_payload
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
                "snapshot_policy": "summary_first",
                "input_summary": input_summary,
                "input_snapshot_meta": input_snapshot_meta,
                "error_summary": str(exc),
                "latency_ms": max(0, int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)),
                "ts": _to_iso_now(),
                "display_output_items": output_builder(
                    node_name=node_name,
                    output_snapshot={},
                    error_summary=str(exc),
                ),
            }
            if input_snapshot_payload is not None:
                payload["input_snapshot"] = input_snapshot_payload
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

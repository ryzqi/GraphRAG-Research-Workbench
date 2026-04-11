"""KB Chat agentic graph 运行时辅助。"""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig

from app.agents.kb_chat_memory import resolve_kb_chat_store_user_id


class KbChatGraphContext(TypedDict, total=False):
    """通过 LangGraph context_schema 传递的运行期只读上下文。"""

    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def build_kb_chat_run_config(
    *, thread_id: str | None, recursion_limit: int
) -> RunnableConfig:
    """为 KB Chat 构建 LangGraph 调用配置。

    `recursion_limit` must stay at top-level config (not under `configurable`).
    """
    config: RunnableConfig = {"recursion_limit": int(recursion_limit)}
    if thread_id:
        config["configurable"] = {"thread_id": thread_id}
    return config


def _coerce_int_setting(value: object, fallback: object, *, minimum: int) -> int:
    if isinstance(value, int):
        return max(minimum, value)
    if isinstance(fallback, int):
        return max(minimum, fallback)
    return minimum


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
            "max_candidates": _coerce_int_setting(
                runtime_config_payload.get("parallel_retrieval_max_branches"),
                getattr(settings, "kb_chat_parallel_retrieval_max_branches", 6),
                minimum=1,
            ),
            "min_queries": _coerce_int_setting(
                runtime_config_payload.get("parallel_retrieval_min_queries"),
                getattr(settings, "kb_chat_parallel_retrieval_min_queries", 2),
                minimum=1,
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

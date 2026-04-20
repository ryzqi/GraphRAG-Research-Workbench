"""KB Chat 长期记忆辅助（基于 LangMem + LangGraph Store）。"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from langchain.messages import AIMessage, HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langmem import (
    ReflectionExecutor,
    create_memory_store_manager,
    create_search_memory_tool,
)
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

from app.core.settings import Settings, get_settings
from app.integrations.chat_model_cache import (
    create_chat_model_cached as create_chat_model,
)
from app.integrations.chat_model_factory import create_fallback_chat_model


logger = logging.getLogger(__name__)


KB_CHAT_MEMORY_SCHEMA = "kb_chat_langmem_v1"
KB_CHAT_MEMORY_KEY = "kb_chat_memory"
KB_CHAT_ANONYMOUS_USER_PREFIX = "anonymous"
KB_CHAT_MEMORY_NAMESPACE_TEMPLATE = ("kb_chat", "{user_id}", "{kb_scope}")
KB_CHAT_MEMORY_KIND = "KbChatFact"


class KbChatFact(BaseModel):
    """KB Chat 场景下由 LangMem 抽取的结构化事实。"""

    subject: str = Field(..., description="事实主体")
    predicate: str = Field(..., description="主体与客体之间的关系")
    object: str = Field(..., description="事实客体或取值")
    kb_scope: str | None = Field(None, description="该事实适用的知识库范围")
    source_question: str | None = Field(None, description="触发抽取的用户问题")
    source_answer: str | None = Field(None, description="触发抽取的助手回答")
    run_id: str | None = Field(None, description="触发抽取的 AgentRun ID")


_KB_CHAT_MEMORY_INSTRUCTIONS = """从 KB Chat 的用户问题与助手回答中抽取可复用的长期事实。
只保留稳定偏好、长期约束、项目背景或后续问答会继续使用的事实。
忽略一次性检索结果、临时表述、纯格式要求和没有长期价值的细节。
事实必须忠实于对话内容，不能补全或猜测未出现的信息。
"""

_reflection_executor_lock = threading.Lock()
_reflection_executor: Any | None = None
_reflection_executor_key: tuple[int, str] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _kb_scope(kb_ids: list[str]) -> str:
    normalized = [str(k).strip() for k in kb_ids if str(k).strip()]
    normalized.sort()
    if not normalized:
        return "kb_all"
    digest = hashlib.sha1(",".join(normalized).encode("utf-8")).hexdigest()[:12]
    return f"kb_{digest}"


def resolve_kb_chat_store_user_id(
    *,
    user_id: str | None,
    thread_id: str | None,
) -> str:
    uid = (user_id or "").strip()
    if uid:
        return uid
    tid = (thread_id or "").strip()
    if tid:
        return f"{KB_CHAT_ANONYMOUS_USER_PREFIX}:{tid}"
    return f"{KB_CHAT_ANONYMOUS_USER_PREFIX}:missing_thread"


def kb_chat_user_namespace(
    *,
    user_id: str | None,
    thread_id: str | None,
    kb_ids: list[str],
) -> tuple[str, ...]:
    uid = resolve_kb_chat_store_user_id(user_id=user_id, thread_id=thread_id)
    return ("kb_chat", uid, _kb_scope(kb_ids))


def kb_chat_thread_key(thread_id: str) -> str:
    tid = (thread_id or "").strip() or "unknown_thread"
    return f"{KB_CHAT_MEMORY_KEY}:{tid}"


def kb_chat_memory_config(
    *,
    user_id: str | None,
    thread_id: str | None,
    kb_ids: list[str],
) -> RunnableConfig:
    return {
        "configurable": {
            "user_id": resolve_kb_chat_store_user_id(
                user_id=user_id,
                thread_id=thread_id,
            ),
            "kb_scope": _kb_scope(kb_ids),
            "thread_id": (thread_id or "").strip() or "unknown_thread",
        }
    }


def _resolve_memory_model(
    *,
    settings: Settings,
    model: BaseChatModel | None,
) -> BaseChatModel:
    if model is not None:
        return model
    model_id = str(getattr(settings, "kb_chat_memory_model_id", "") or "").strip()
    if model_id:
        return create_fallback_chat_model(
            fallback_model_id=model_id,
            settings=settings,
            use_previous_response_id=False,
        )
    return create_chat_model(settings=settings, use_previous_response_id=False)


def _memory_model_cache_key(settings: Settings, model: BaseChatModel | None) -> str:
    if model is not None:
        return f"injected:{id(model)}"
    model_id = str(getattr(settings, "kb_chat_memory_model_id", "") or "").strip()
    if model_id:
        return f"fallback:{model_id}"
    return "active-runtime-model"


def build_kb_chat_memory_manager(
    *,
    store: BaseStore,
    settings: Settings | None = None,
    model: BaseChatModel | None = None,
):
    cfg = settings or get_settings()
    return create_memory_store_manager(
        _resolve_memory_model(settings=cfg, model=model),
        namespace=KB_CHAT_MEMORY_NAMESPACE_TEMPLATE,
        schemas=[KbChatFact],
        instructions=_KB_CHAT_MEMORY_INSTRUCTIONS,
        enable_inserts=True,
        enable_deletes=True,
        query_limit=int(getattr(cfg, "kb_chat_memory_search_limit", 5)),
        store=store,
    )


def build_kb_chat_search_memory_tool(*, store: BaseStore):
    return create_search_memory_tool(
        KB_CHAT_MEMORY_NAMESPACE_TEMPLATE,
        store=store,
        name="search_kb_chat_memory",
    )


def _get_reflection_executor(
    *,
    manager: Any,
    store: BaseStore,
    model_cache_key: str,
) -> Any:
    global _reflection_executor, _reflection_executor_key

    key = (id(store), model_cache_key)
    with _reflection_executor_lock:
        if _reflection_executor is not None and _reflection_executor_key == key:
            return _reflection_executor
        if _reflection_executor is not None:
            try:
                _reflection_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:  # pragma: no cover - best effort
                logger.warning("关闭旧 KB Chat LangMem executor 失败", exc_info=True)
        _reflection_executor = ReflectionExecutor(manager, store=store)
        _reflection_executor_key = key
        return _reflection_executor


def shutdown_kb_chat_memory_reflection_executor(
    *,
    wait: bool = False,
    cancel_futures: bool = True,
) -> None:
    global _reflection_executor, _reflection_executor_key

    with _reflection_executor_lock:
        executor = _reflection_executor
        _reflection_executor = None
        _reflection_executor_key = None
    if executor is not None:
        executor.shutdown(wait=wait, cancel_futures=cancel_futures)


def _future_log_callback(future: Any) -> None:
    try:
        future.result()
    except Exception:  # pragma: no cover - best effort
        logger.warning("KB Chat LangMem 后台反射失败", exc_info=True)


def _reflection_task_id(
    *,
    user_id: str,
    thread_id: str,
    run_id: str | None,
) -> str:
    rid = str(run_id or "").strip()
    if rid:
        return f"kb_chat_memory:{user_id}:{thread_id}:run:{rid}"
    return f"kb_chat_memory:{user_id}:{thread_id}:ts:{_now_iso()}"


def _extract_fact_content(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, KbChatFact):
        return raw.model_dump(mode="json")
    if not isinstance(raw, dict):
        return None
    if raw.get("kind") == KB_CHAT_MEMORY_KIND and isinstance(raw.get("content"), dict):
        return KbChatFact.model_validate(raw["content"]).model_dump(mode="json")
    if {"subject", "predicate", "object"}.issubset(raw):
        return KbChatFact.model_validate(raw).model_dump(mode="json")
    return None


def _memory_entry_from_search_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        value = item.get("value")
        key = item.get("key")
        namespace = item.get("namespace")
        score = item.get("score")
    else:
        value = getattr(item, "value", None)
        key = getattr(item, "key", "")
        namespace = getattr(item, "namespace", ())
        score = getattr(item, "score", None)
    fact = _extract_fact_content(value)
    if fact is None:
        return None
    return {
        **fact,
        "memory_key": str(key or ""),
        "memory_namespace": [str(part) for part in (namespace or ())],
        "memory_score": score,
    }


async def aget_kb_chat_memory(
    *,
    store: BaseStore,
    user_id: str,
    thread_id: str,
    kb_ids: list[str],
    query: str | None = None,
    limit: int = 5,
) -> dict[str, Any] | None:
    tool = build_kb_chat_search_memory_tool(store=store)
    raw = await tool.ainvoke(
        {"query": (query or "").strip(), "limit": max(1, int(limit))},
        config=kb_chat_memory_config(
            user_id=user_id,
            thread_id=thread_id,
            kb_ids=kb_ids,
        ),
    )
    try:
        results = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None
    if not isinstance(results, list):
        return None
    entries = [
        entry
        for item in results
        if (entry := _memory_entry_from_search_item(item)) is not None
    ]
    if not entries:
        return None
    return {
        "schema": KB_CHAT_MEMORY_SCHEMA,
        "updated_at": _now_iso(),
        "entries": entries,
    }


def _truncate(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return f"{t[: max_chars - 1].rstrip()}…"


def render_kb_chat_memory_snippet(memory: dict[str, Any]) -> str:
    entries = memory.get("entries")
    if not isinstance(entries, list) or not entries:
        return ""
    last = [e for e in entries if isinstance(e, dict)][-3:]
    if not last:
        return ""

    lines: list[str] = ["长期记忆："]
    for e in last:
        subject = _truncate(str(e.get("subject") or ""), 80)
        predicate = _truncate(str(e.get("predicate") or ""), 80)
        obj = _truncate(str(e.get("object") or ""), 160)
        if subject and predicate and obj:
            lines.append(f"- {subject} {predicate} {obj}")
            continue
        q = _truncate(str(e.get("q") or ""), 120)
        a = _truncate(str(e.get("a") or ""), 200)
        if q and a:
            lines.append(f"- Q: {q}\n  A: {a}")
    return "\n".join(lines).strip()


async def append_kb_chat_memory_entry(
    *,
    store: BaseStore,
    user_id: str,
    thread_id: str,
    kb_ids: list[str],
    question: str,
    answer: str,
    run_id: str | None,
    settings: Settings | None = None,
    model: BaseChatModel | None = None,
    reflection_delay_seconds: int | None = None,
) -> None:
    """使用 LangMem 从成功问答中抽取长期记忆。"""
    q = _truncate(question, 300)
    a = _truncate(answer, 800)
    if not q or not a:
        return

    cfg = settings or get_settings()
    manager = build_kb_chat_memory_manager(store=store, settings=cfg, model=model)
    config = kb_chat_memory_config(user_id=user_id, thread_id=thread_id, kb_ids=kb_ids)
    resolved_user_id = str(config["configurable"]["user_id"])
    resolved_thread_id = str(config["configurable"]["thread_id"])
    payload = {
        "messages": [
            HumanMessage(content=q),
            AIMessage(content=f"{a}\n\nrun_id: {run_id or ''}".strip()),
        ],
        "max_steps": int(getattr(cfg, "kb_chat_memory_max_steps", 1)),
    }
    delay_seconds = (
        int(reflection_delay_seconds)
        if reflection_delay_seconds is not None
        else int(getattr(cfg, "kb_chat_memory_reflection_delay_seconds", 300))
    )
    if delay_seconds > 0:
        executor = _get_reflection_executor(
            manager=manager,
            store=store,
            model_cache_key=_memory_model_cache_key(cfg, model),
        )
        future = executor.submit(
            payload,
            config=config,
            after_seconds=delay_seconds,
            thread_id=_reflection_task_id(
                user_id=resolved_user_id,
                thread_id=resolved_thread_id,
                run_id=run_id,
            ),
        )
        future.add_done_callback(_future_log_callback)
        return

    await manager.ainvoke(payload, config=config)

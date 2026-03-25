"""KB Chat 记忆辅助函数（基于 LangGraph Store）。

本模块维护的记忆载荷具备以下特性：
- 结构化：使用 JSON 字典
- 有界：固定大小列表
- 支持 TTL：优先使用 store 原生 ttl，不支持时退回包装层
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from langgraph.store.base import BaseStore


KB_CHAT_MEMORY_SCHEMA = "kb_chat_user_memory_v1"
KB_CHAT_MEMORY_KEY = "kb_chat_memory"
KB_CHAT_ANONYMOUS_USER_PREFIX = "anonymous"

# 保守默认值：仅保留较小窗口，并在一周后过期。
KB_CHAT_MEMORY_MAX_ENTRIES = 5
KB_CHAT_MEMORY_TTL_SECONDS = 7 * 24 * 60 * 60


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
    return ("kb_chat", "user", uid, _kb_scope(kb_ids))


def kb_chat_thread_key(thread_id: str) -> str:
    tid = (thread_id or "").strip() or "unknown_thread"
    return f"{KB_CHAT_MEMORY_KEY}:{tid}"


def _wrap_value_with_ttl(value: dict[str, Any], *, ttl_seconds: int) -> dict[str, Any]:
    expires_at = (_now() + timedelta(seconds=int(ttl_seconds))).isoformat()
    return {"_ttl": {"expires_at": expires_at}, "payload": value}


def _unwrap_value_with_ttl(value: dict[str, Any]) -> dict[str, Any] | None:
    ttl = value.get("_ttl")
    payload = value.get("payload")
    if not isinstance(ttl, dict) or not isinstance(payload, dict):
        return None
    expires_at = ttl.get("expires_at")
    if not isinstance(expires_at, str) or not expires_at:
        return None
    try:
        deadline = datetime.fromisoformat(expires_at)
    except ValueError:
        return None
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if _now() >= deadline:
        return None
    return payload


async def aget_kb_chat_memory(
    *,
    store: BaseStore,
    user_id: str,
    thread_id: str,
    kb_ids: list[str],
) -> dict[str, Any] | None:
    ns = kb_chat_user_namespace(user_id=user_id, thread_id=thread_id, kb_ids=kb_ids)
    item = await store.aget(ns, kb_chat_thread_key(thread_id))
    if item is None:
        return None
    raw = getattr(item, "value", None)
    if not isinstance(raw, dict):
        return None
    if raw.get("schema") == KB_CHAT_MEMORY_SCHEMA:
        return raw
    # 对不支持原生 TTL 的 store，退回到 TTL 包装层。
    return _unwrap_value_with_ttl(raw)


async def aput_kb_chat_memory(
    *,
    store: BaseStore,
    user_id: str,
    thread_id: str,
    kb_ids: list[str],
    memory: dict[str, Any],
    ttl_seconds: int,
) -> None:
    ns = kb_chat_user_namespace(user_id=user_id, thread_id=thread_id, kb_ids=kb_ids)
    key = kb_chat_thread_key(thread_id)
    if store.supports_ttl:
        await store.aput(ns, key, memory, ttl=float(ttl_seconds))
        return
    wrapped = _wrap_value_with_ttl(memory, ttl_seconds=ttl_seconds)
    await store.aput(ns, key, wrapped)


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

    lines: list[str] = ["会话记忆（近期）："]
    for e in last:
        q = _truncate(str(e.get("q") or ""), 120)
        a = _truncate(str(e.get("a") or ""), 200)
        if not q or not a:
            continue
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
    ttl_seconds: int = KB_CHAT_MEMORY_TTL_SECONDS,
    max_entries: int = KB_CHAT_MEMORY_MAX_ENTRIES,
) -> None:
    """向用户记忆追加一条有界的问答记录。"""
    existing = await aget_kb_chat_memory(
        store=store, user_id=user_id, thread_id=thread_id, kb_ids=kb_ids
    )
    entries: list[dict[str, Any]] = []
    if isinstance(existing, dict):
        raw_entries = existing.get("entries")
        if isinstance(raw_entries, list):
            entries = [e for e in raw_entries if isinstance(e, dict)]

    q = _truncate(question, 300)
    a = _truncate(answer, 800)
    if not q or not a:
        return

    entries.append(
        {
            "q": q,
            "a": a,
            "thread_id": str(thread_id),
            "kb_ids": [str(k) for k in kb_ids if str(k).strip()],
            "run_id": str(run_id) if run_id else None,
            "ts": _now_iso(),
        }
    )
    if max_entries > 0 and len(entries) > max_entries:
        entries = entries[-max_entries:]

    payload: dict[str, Any] = {
        "schema": KB_CHAT_MEMORY_SCHEMA,
        "updated_at": _now_iso(),
        "entries": entries,
    }
    await aput_kb_chat_memory(
        store=store,
        user_id=user_id,
        thread_id=thread_id,
        kb_ids=kb_ids,
        memory=payload,
        ttl_seconds=ttl_seconds,
    )

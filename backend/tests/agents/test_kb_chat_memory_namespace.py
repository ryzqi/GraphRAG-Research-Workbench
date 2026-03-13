from __future__ import annotations

from app.agents.kb_chat_memory import (
    kb_chat_user_namespace,
    resolve_kb_chat_store_user_id,
)


def test_resolve_kb_chat_store_user_id_uses_thread_scoped_anonymous_fallback() -> None:
    assert (
        resolve_kb_chat_store_user_id(user_id="", thread_id="thread-1")
        == "anonymous:thread-1"
    )


def test_kb_chat_user_namespace_never_falls_back_to_shared_local() -> None:
    namespace = kb_chat_user_namespace(
        user_id="",
        thread_id="thread-1",
        kb_ids=["kb-1"],
    )

    assert namespace[:3] == ("kb_chat", "user", "anonymous:thread-1")
    assert "local" not in namespace

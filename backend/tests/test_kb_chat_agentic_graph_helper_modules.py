from __future__ import annotations

from types import SimpleNamespace

from app.agents import kb_chat_agentic_graph
from app.agents.kb_chat_agentic_graph_runtime import (
    KbChatGraphContext,
    build_kb_chat_run_config,
    build_kb_chat_run_context,
)


def test_kb_chat_graph_runtime_helpers_and_reexports() -> None:
    settings = SimpleNamespace(
        kb_chat_parallel_retrieval_max_branches=6,
        kb_chat_parallel_retrieval_min_queries=2,
        kb_chat_parallel_retrieval_include_main=True,
    )

    config = build_kb_chat_run_config(thread_id="thread-1", recursion_limit=7)
    context: KbChatGraphContext = build_kb_chat_run_context(
        thread_id=None,
        state={
            "memory_keys": {
                "thread_id": "thread-1",
                "user_id": "user-1",
                "kb_ids": ["kb-a", "", 123],
            },
            "runtime_config": {
                "parallel_retrieval_max_branches": 0,
                "parallel_retrieval_min_queries": 3,
                "parallel_retrieval_include_main": False,
            },
        },
        settings=settings,
    )

    assert config == {"recursion_limit": 7, "configurable": {"thread_id": "thread-1"}}
    assert context["thread_id"] == "thread-1"
    assert context["user_id"] == "user-1"
    assert context["kb_ids"] == ["kb-a"]
    assert context["runtime_config"]["parallel_retrieval_min_queries"] == 3
    assert context["message_budget"] == {
        "max_candidates": 1,
        "min_queries": 3,
        "include_main": False,
    }
    assert kb_chat_agentic_graph.build_kb_chat_run_config is build_kb_chat_run_config
    assert kb_chat_agentic_graph.build_kb_chat_run_context is build_kb_chat_run_context

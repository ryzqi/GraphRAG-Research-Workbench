from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.kb_chat_agentic.preprocess import merge_context
from app.agents.kb_chat_agentic.reflection import dispatch_subqueries, kb_retrieve_context
from app.agents.retrieval_subgraph import _retrieval_budget_plan


def _settings(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "app_env": "test",
        "kb_chat_json_safe_policy": "stringify",
        "memory_enabled": False,
        "retrieval_default_top_k": 5,
        "retrieval_max_top_k": 50,
        "kb_chat_max_total_rounds": 3,
        "kb_chat_parallel_retrieval_min_queries": 2,
        "kb_chat_parallel_retrieval_max_branches": 6,
        "kb_chat_parallel_retrieval_include_main": True,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _runtime_context(
    *,
    thread_id: str = "thread-ctx",
    user_id: str = "user-ctx",
    kb_ids: list[str] | None = None,
    runtime_config: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        context={
            "thread_id": thread_id,
            "user_id": user_id,
            "kb_ids": kb_ids or [],
            "runtime_config": runtime_config or {},
        },
        store=None,
    )


def test_retrieval_budget_plan_does_not_write_runtime_config_state() -> None:
    result = _retrieval_budget_plan(
        {
            "complexity_level": "moderate",
            "query_items": [{"kind": "main", "query": "问题"}],
            "stage_summaries": {},
        },
        settings=_settings(),
    )

    assert "runtime_config" not in result
    assert result["retrieval_budget"]["per_query_top_k"] >= 1


@pytest.mark.asyncio
async def test_dispatch_subqueries_branch_payload_omits_state_runtime_keys() -> None:
    command = await dispatch_subqueries(
        {
            "query_strategy": "direct",
            "query_items": [
                {"kind": "main", "query": "主问题", "index": 0},
                {"kind": "hyde", "query": "扩展问题", "index": 1},
            ],
            "loop_counts": {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0},
            "memory_keys": {"user_id": "stale-user", "kb_ids": ["stale-kb"]},
            "runtime_config": {"retrieval_top_k": 99},
            "stage_summaries": {},
        },
        settings=_settings(),
        runtime=_runtime_context(kb_ids=["kb-live"]),
    )

    payloads = [task.arg for task in command.goto]
    assert payloads
    assert all("memory_keys" not in payload for payload in payloads)
    assert all("runtime_config" not in payload for payload in payloads)


@pytest.mark.asyncio
async def test_kb_retrieve_context_prefers_runtime_context_for_scope_and_runtime_config() -> None:
    kb_tool = SimpleNamespace(ainvoke=AsyncMock(return_value="[S1] 命中证据"))

    await kb_retrieve_context(
        {
            "user_input": "问题",
            "loop_counts": {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0},
            "metrics": {},
            "stage_summaries": {},
        },
        settings=_settings(),
        kb_tool=kb_tool,
        runtime=_runtime_context(
            kb_ids=["kb-live"],
            runtime_config={"retrieval_top_k": 7},
        ),
    )

    payload = kb_tool.ainvoke.await_args.args[0]
    assert payload["kb_ids"] == ["kb-live"]
    assert payload["top_k"] == 7
    assert "timeout_seconds" not in payload


@pytest.mark.asyncio
async def test_merge_context_loads_memory_from_runtime_context_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess._generate_summary_from_turns",
        AsyncMock(return_value=""),
    )
    fake_memory_get = AsyncMock(
        return_value={"summary": "记忆", "thread_id": "thread-ctx", "kb_ids": ["kb-live"]}
    )
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess.aget_kb_chat_memory",
        fake_memory_get,
    )
    monkeypatch.setattr(
        "app.agents.kb_chat_agentic.preprocess.render_kb_chat_memory_snippet",
        lambda _mem: "记忆片段",
    )

    runtime = _runtime_context(thread_id="thread-ctx", user_id="user-ctx", kb_ids=["kb-live"])
    runtime.store = object()

    result = await merge_context(
        {
            "messages": [],
            "user_input": "当前问题",
            "metrics": {},
            "stage_summaries": {},
        },
        runtime=runtime,
        settings=_settings(memory_enabled=True),
    )

    assert result["context_frame"]["memory_snippet"] == "记忆片段"
    fake_memory_get.assert_awaited_once()
    kwargs = fake_memory_get.await_args.kwargs
    assert kwargs["user_id"] == "user-ctx"
    assert kwargs["thread_id"] == "thread-ctx"
    assert kwargs["kb_ids"] == ["kb-live"]

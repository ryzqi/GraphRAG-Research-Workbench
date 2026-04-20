from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain.messages import HumanMessage
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.store.memory import InMemoryStore
from pydantic import PrivateAttr

from app.agents.kb_chat_agentic.preprocess_context_nodes import merge_context
from app.agents.kb_chat_memory import (
    append_kb_chat_memory_entry,
    build_kb_chat_search_memory_tool,
    kb_chat_thread_key,
    kb_chat_user_namespace,
)
from app.core.settings import Settings


class _ToolCapableFakeChatModel(FakeMessagesListChatModel):
    _bound_tool_name_batches: list[list[str]] = PrivateAttr(default_factory=list)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001
        del tool_choice, kwargs
        self._bound_tool_name_batches.append([
            getattr(tool, "__name__", getattr(tool, "name", str(tool)))
            for tool in tools
        ])
        return self


class _RecordingFuture:
    def __init__(self) -> None:
        self.cancelled = False
        self.callbacks = []

    def cancel(self) -> None:
        self.cancelled = True

    def add_done_callback(self, callback):  # noqa: ANN001
        self.callbacks.append(callback)


class _RecordingReflectionExecutor:
    instances: list["_RecordingReflectionExecutor"] = []

    def __init__(self, manager, *, store):  # noqa: ANN001
        self.manager = manager
        self.store = store
        self.submissions = []
        self.pending_by_thread_id: dict[str, _RecordingFuture] = {}
        self.shutdown_calls = []
        type(self).instances.append(self)

    def submit(self, payload, *, config, after_seconds, thread_id):  # noqa: ANN001
        if thread_id in self.pending_by_thread_id:
            self.pending_by_thread_id[thread_id].cancel()
        future = _RecordingFuture()
        self.pending_by_thread_id[thread_id] = future
        self.submissions.append(
            {
                "payload": payload,
                "config": config,
                "after_seconds": after_seconds,
                "thread_id": thread_id,
                "future": future,
            }
        )
        return future

    def shutdown(self, *, wait=True, cancel_futures=False):  # noqa: ANN001
        self.shutdown_calls.append(
            {"wait": wait, "cancel_futures": cancel_futures}
        )


@pytest.mark.asyncio
async def test_append_kb_chat_memory_entry_writes_langmem_fact_namespace() -> None:
    store = InMemoryStore()
    model = _ToolCapableFakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "fact-1",
                        "name": "KbChatFact",
                        "args": {
                            "subject": "部署窗口",
                            "predicate": "偏好",
                            "object": "凌晨两点",
                            "kb_scope": "kb_all",
                        },
                    }
                ],
            )
        ]
    )

    ns = kb_chat_user_namespace(
        user_id="user-1",
        thread_id="thread-1",
        kb_ids=[],
    )

    await append_kb_chat_memory_entry(
        store=store,
        user_id="user-1",
        thread_id="thread-1",
        kb_ids=[],
        question="请记住部署窗口",
        answer="部署窗口偏好为凌晨两点。",
        run_id="run-1",
        model=model,
        reflection_delay_seconds=0,
    )

    items = await store.asearch(ns)

    assert ns == ("kb_chat", "user-1", "kb_all")
    assert any("KbChatFact" in batch for batch in model._bound_tool_name_batches)
    assert len(items) == 1
    assert items[0].value == {
        "kind": "KbChatFact",
        "content": {
            "subject": "部署窗口",
            "predicate": "偏好",
            "object": "凌晨两点",
            "kb_scope": "kb_all",
            "source_question": None,
            "source_answer": None,
            "run_id": None,
        },
    }
    assert await store.aget(ns, kb_chat_thread_key("thread-1")) is None


@pytest.mark.asyncio
async def test_delayed_reflection_keeps_each_successful_run_pending() -> None:
    store = InMemoryStore()
    model = _ToolCapableFakeChatModel(responses=[])
    _RecordingReflectionExecutor.instances.clear()

    with patch(
        "app.agents.kb_chat_memory.ReflectionExecutor",
        _RecordingReflectionExecutor,
    ):
        await append_kb_chat_memory_entry(
            store=store,
            user_id="user-1",
            thread_id="thread-1",
            kb_ids=[],
            question="第一轮要记住什么？",
            answer="第一轮事实。",
            run_id="run-1",
            model=model,
            reflection_delay_seconds=300,
        )
        await append_kb_chat_memory_entry(
            store=store,
            user_id="user-1",
            thread_id="thread-1",
            kb_ids=[],
            question="第二轮要记住什么？",
            answer="第二轮事实。",
            run_id="run-2",
            model=model,
            reflection_delay_seconds=300,
        )

    assert len(_RecordingReflectionExecutor.instances) == 1
    executor = _RecordingReflectionExecutor.instances[0]
    thread_ids = [submission["thread_id"] for submission in executor.submissions]
    assert len(thread_ids) == 2
    assert len(set(thread_ids)) == 2
    assert all(
        not submission["future"].cancelled for submission in executor.submissions
    )
    assert any("run-1" in thread_id for thread_id in thread_ids)
    assert any("run-2" in thread_id for thread_id in thread_ids)


@pytest.mark.asyncio
async def test_kb_chat_search_memory_tool_uses_langmem_namespace() -> None:
    store = InMemoryStore()
    ns = kb_chat_user_namespace(
        user_id="user-1",
        thread_id="thread-1",
        kb_ids=[],
    )
    await store.aput(
        ns,
        "fact-1",
        {
            "kind": "KbChatFact",
            "content": {
                "subject": "部署窗口",
                "predicate": "偏好",
                "object": "凌晨两点",
            },
        },
    )

    tool = build_kb_chat_search_memory_tool(store=store)
    result = await tool.ainvoke(
        {"query": "部署窗口", "limit": 5},
        config={"configurable": {"user_id": "user-1", "kb_scope": "kb_all"}},
    )

    assert tool.name == "search_kb_chat_memory"
    assert '"key":"fact-1"' in result
    assert '"subject":"部署窗口"' in result


@pytest.mark.asyncio
async def test_merge_context_reads_langmem_fact_memory_snippet() -> None:
    store = InMemoryStore()
    ns = kb_chat_user_namespace(
        user_id="user-1",
        thread_id="thread-1",
        kb_ids=[],
    )
    await store.aput(
        ns,
        "fact-1",
        {
            "kind": "KbChatFact",
            "content": {
                "subject": "部署窗口",
                "predicate": "偏好",
                "object": "凌晨两点",
                "kb_scope": "kb_all",
            },
        },
    )

    result = await merge_context(
        {
            "user_input": "部署窗口是什么时候？",
            "messages": [HumanMessage(content="部署窗口是什么时候？")],
            "metrics": {},
            "stage_summaries": {},
        },
        SimpleNamespace(
            context={"thread_id": "thread-1", "user_id": "user-1", "kb_ids": []},
            store=store,
        ),
        Settings(MEMORY_ENABLED=True, SUMMARY_ENABLED=False),
    )

    assert result["stage_summaries"]["merge_context"]["memory_included"] is True
    assert "长期记忆" in result["merged_context"]
    assert "部署窗口 偏好 凌晨两点" in result["merged_context"]


@pytest.mark.asyncio
async def test_merge_context_records_memory_recall_precision_metrics() -> None:
    store = InMemoryStore()
    ns = kb_chat_user_namespace(
        user_id="user-1",
        thread_id="thread-1",
        kb_ids=[],
    )
    await store.aput(
        ns,
        "fact-1",
        {
            "kind": "KbChatFact",
            "content": {
                "subject": "部署窗口",
                "predicate": "偏好",
                "object": "凌晨两点",
                "kb_scope": "kb_all",
            },
        },
    )
    await store.aput(
        ns,
        "fact-2",
        {
            "kind": "KbChatFact",
            "content": {
                "subject": "部署窗口",
                "predicate": "偏好",
                "object": "凌晨两点",
                "kb_scope": "kb_all",
            },
        },
    )

    result = await merge_context(
        {
            "user_input": "部署窗口是什么时候？",
            "messages": [HumanMessage(content="部署窗口是什么时候？")],
            "metrics": {},
            "stage_summaries": {},
        },
        SimpleNamespace(
            context={"thread_id": "thread-1", "user_id": "user-1", "kb_ids": []},
            store=store,
        ),
        Settings(MEMORY_ENABLED=True, SUMMARY_ENABLED=False),
    )

    summary = result["stage_summaries"]["merge_context"]
    assert summary["memory_candidates"] == 2
    assert summary["memory_retained"] == 2
    assert summary["memory_retained_distinct"] == 1
    assert summary["memory_rendered"] == 1
    assert summary["memory_recall_precision"] == 1.0

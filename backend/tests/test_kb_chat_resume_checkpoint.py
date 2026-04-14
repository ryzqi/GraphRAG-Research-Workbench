from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain.messages import AIMessage, HumanMessage

from app.agents.kb_chat_contracts import STATE_SCHEMA_V3
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_session import AgentMode, ChatSession, ChatSessionType
from app.schemas.chats import KbChatConfig
from app.services import kb_chat_service_execution as kb_execution


class _FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_calls = 0
        self.commit_calls = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1


class _FakeGraph:
    def make_run_context(self, **kwargs):
        return {
            "thread_id": kwargs.get("thread_id"),
            "runtime_config": kwargs.get("runtime_config"),
        }

    def compile(self, **kwargs):
        return {"compiled": True, **kwargs}


@pytest.mark.asyncio
async def test_prepare_kb_chat_execution_uses_checkpoint_tuple_id_for_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = ChatSession(
        id=uuid4(),
        session_type=ChatSessionType.KB_CHAT,
        selected_kb_ids=[],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
        kb_chat_config=None,
    )
    run = AgentRun(
        id=uuid4(),
        run_type=AgentRunType.KB_ANSWER,
        session_id=session.id,
        question="之前的问题",
        selected_kb_ids=[],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
        status=AgentRunStatus.RUNNING,
    )
    checkpoint_id = "checkpoint-latest-123"
    checkpoint_tuple = SimpleNamespace(
        checkpoint={
            "id": checkpoint_id,
            "channel_values": {
                "schema_version": STATE_SCHEMA_V3,
                "messages": [
                    HumanMessage(content="旧问题"),
                    AIMessage(content="旧回答"),
                ],
            },
        }
    )

    async def _fake_build_tool_registry(**kwargs):
        del kwargs
        return ([SimpleNamespace(name="kb_retrieve")], {})

    monkeypatch.setattr(
        kb_execution.CheckpointManager,
        "get_state",
        AsyncMock(return_value=checkpoint_tuple),
    )
    monkeypatch.setattr(
        kb_execution.CheckpointManager,
        "get_checkpointer",
        lambda: "fake-checkpointer",
    )
    monkeypatch.setattr(
        kb_execution,
        "build_kb_retrieve_tool",
        lambda **kwargs: SimpleNamespace(name="kb_retrieve", kwargs=kwargs),
    )
    monkeypatch.setattr(
        kb_execution,
        "build_tool_registry",
        _fake_build_tool_registry,
    )
    monkeypatch.setattr(
        kb_execution,
        "create_chat_model",
        lambda **kwargs: SimpleNamespace(model="fake", kwargs=kwargs),
    )
    monkeypatch.setattr(
        kb_execution.StoreManager,
        "get_store",
        lambda: None,
    )

    graph = _FakeGraph()
    service = SimpleNamespace(
        _db=_FakeDb(),
        _summary_service=SimpleNamespace(load_latest_summary=AsyncMock(return_value=None)),
        _load_history=AsyncMock(return_value=[]),
        _context_builder=SimpleNamespace(
            build_history_messages=lambda **kwargs: ([], {}, {}),
            build_metrics=lambda **kwargs: {"history": "ok"},
        ),
        _settings=SimpleNamespace(),
        _retrieval=object(),
        _prompts=SimpleNamespace(render_with_few_shot=lambda _: "kb system prompt"),
        _resolve_session_kb_chat_config=lambda _session: KbChatConfig(),
        _apply_gray_release_rollback_policy=AsyncMock(
            side_effect=lambda *, kb_chat_config: (kb_chat_config, None)
        ),
        _to_retrieval_overrides=lambda _config: {},
        _safe_non_negative_int=lambda value: value if isinstance(value, int) else None,
        _resolve_kb_chat_user_id=lambda _session: "user-1",
        _build_graph=lambda **kwargs: graph,
    )
    service._sanitize_checkpoint_messages = lambda messages: (
        kb_execution._sanitize_checkpoint_messages(None, messages)
    )
    service._sanitize_checkpoint_state = lambda state: (
        kb_execution._sanitize_checkpoint_state(service, state)
    )
    service._build_checkpoint_restore_audit = lambda **kwargs: (
        kb_execution._build_checkpoint_restore_audit(None, **kwargs)
    )

    exec_ctx = await kb_execution._prepare_kb_chat_execution(
        service,
        session=session,
        user_content="新的问题",
        run=run,
    )

    assert exec_ctx.resume_checkpoint_id == checkpoint_id
    assert exec_ctx.resume_checkpoint_id != str(run.id)
    assert exec_ctx.state["stage_summaries"]["checkpoint_restore"][
        "checkpoint_restore_source_checkpoint_id"
    ] == checkpoint_id

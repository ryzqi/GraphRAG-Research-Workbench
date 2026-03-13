from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain.messages import AIMessage, HumanMessage, SystemMessage

import app.services.kb_chat_service as kb_chat_service_module
from app.agents.kb_chat_contracts import STATE_SCHEMA_V3
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_session import AgentMode
from app.core.checkpoint import CheckpointManager
from app.services.kb_chat_service import KbChatService


def test_sanitize_checkpoint_state_filters_transient_fields_and_tool_messages() -> None:
    plan = KbChatService._sanitize_checkpoint_state(
        {
            "messages": [
                SystemMessage(content="system"),
                HumanMessage(content="question"),
                AIMessage(
                    content="tool-call",
                    additional_kwargs={"tool_calls": [{"id": "call-1"}]},
                ),
                AIMessage(content="clarification"),
            ],
            "user_input": "stale question",
            "pending_tool_calls": [{"name": "kb_retrieve"}],
            "reflection": {"action": "clarify"},
            "preprocess_next": "force_exit",
            "answer_review_runs": [{"judge": "stale"}],
        }
    )

    assert [message.content for message in plan.messages] == [
        "system",
        "question",
        "clarification",
    ]
    assert set(plan.reset_fields) >= {
        "user_input",
        "pending_tool_calls",
        "reflection",
        "preprocess_next",
        "answer_review_runs",
    }
    assert set(plan.legacy_fields) == {"messages_filtered", "schema_version"}


def test_checkpoint_state_summary_redacts_raw_channel_values() -> None:
    summary = CheckpointManager.summarize_channel_values(
        {
            "schema_version": STATE_SCHEMA_V3,
            "messages": [HumanMessage(content="q"), AIMessage(content="a")],
            "stage_summaries": {
                "checkpoint_restore": {
                    "checkpoint_restore_applied": True,
                    "checkpoint_restore_source_checkpoint_id": "cp-1",
                    "checkpoint_restore_reset_fields": ["reflection"],
                    "checkpoint_restore_legacy_fields": [],
                },
                "force_exit": {"reason": "clarify"},
            },
            "metrics": {"context": {"history": 2}},
            "loop_counts": {
                "total_rounds": 1,
                "retrieval_retries": 0,
                "generation_retries": 0,
            },
            "final_answer": "should not leak",
        }
    )

    assert summary["message_count"] == 2
    assert summary["schema_version"] == STATE_SCHEMA_V3
    assert "final_answer" in summary["field_names"]
    assert "force_exit" in summary["stage_summary_keys"]
    assert summary["checkpoint_restore"]["checkpoint_restore_source_checkpoint_id"] == "cp-1"
    assert "final_answer" not in summary


def test_build_node_io_summary_for_answer_subgraph_reads_stage_summary() -> None:
    summary = KbChatService._build_node_io_summary(
        node="answer_subgraph",
        update={
            "degrade_reason": "review_failed",
            "stage_summaries": {
                "answer_subgraph": {
                    "next_step": "transform_query",
                    "reason": "missing_citations",
                }
            },
        },
    )

    assert summary == {
        "next_step": "transform_query",
        "reason": "missing_citations",
        "degrade_reason": "review_failed",
    }


class _FakeConfig:
    def model_dump(self, *, mode: str = "json") -> dict[str, int]:
        assert mode == "json"
        return {"retrieval_top_k": 5}


class _FakeGraph:
    def make_run_context(
        self,
        *,
        thread_id: str,
        state: dict[str, object],
        user_id: str | None = None,
        kb_ids: list[str] | None = None,
        runtime_config: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "thread_id": thread_id,
            "user_id": user_id or "",
            "kb_ids": kb_ids or [],
            "runtime_config": runtime_config or {},
        }

    def compile(self, **_: object) -> object:
        return object()


def _build_service(monkeypatch: pytest.MonkeyPatch) -> KbChatService:
    service = object.__new__(KbChatService)
    service._db = SimpleNamespace(
        add=lambda _obj: None,
        flush=AsyncMock(),
        commit=AsyncMock(),
    )
    service._settings = SimpleNamespace(
        context_history_max_messages=8,
        memory_enabled=False,
    )
    service._summary_service = SimpleNamespace(load_latest_summary=AsyncMock(return_value=None))
    service._load_history = AsyncMock(return_value=[])
    service._context_builder = SimpleNamespace(
        build_history_messages=lambda **_: ([], {}, {}),
        build_metrics=lambda **_: {"history_messages": 0},
    )
    service._resolve_session_kb_chat_config = lambda _session: _FakeConfig()
    service._apply_gray_release_rollback_policy = AsyncMock(return_value=(_FakeConfig(), None))
    service._to_retrieval_overrides = lambda _config: {}
    service._retrieval = object()
    service._prompts = SimpleNamespace(render_with_few_shot=lambda _name: "system prompt")
    service._build_graph = lambda **_: _FakeGraph()

    monkeypatch.setattr(kb_chat_service_module, "build_kb_retrieve_tool", lambda **_: object())
    monkeypatch.setattr(
        kb_chat_service_module,
        "build_tool_registry",
        AsyncMock(return_value=([], {})),
    )
    monkeypatch.setattr(kb_chat_service_module, "create_chat_model", lambda **_: object())
    monkeypatch.setattr(kb_chat_service_module.StoreManager, "get_store", lambda: None)
    monkeypatch.setattr(kb_chat_service_module.CheckpointManager, "get_checkpointer", lambda: object())
    return service


@pytest.mark.asyncio
async def test_prepare_kb_chat_execution_rebuilds_fresh_state_without_checkpoint_transients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(monkeypatch)
    session = SimpleNamespace(
        id=uuid.uuid4(),
        selected_kb_ids=[],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
        kb_chat_config=None,
    )
    checkpoint_tuple = SimpleNamespace(
        checkpoint={
            "id": "cp-fresh",
            "channel_values": {
                "messages": [
                    SystemMessage(content="stale system"),
                    HumanMessage(content="stale question"),
                    AIMessage(content="stale clarification"),
                ],
                "user_input": "stale question",
                "reflection": {"action": "clarify"},
                "preprocess_next": "force_exit",
            },
        }
    )
    monkeypatch.setattr(
        kb_chat_service_module.CheckpointManager,
        "get_state",
        AsyncMock(return_value=checkpoint_tuple),
    )

    execution = await service._prepare_kb_chat_execution(
        session=session,
        user_content="new question",
    )

    assert execution.state["user_input"] == "new question"
    assert [message.content for message in execution.state["messages"]] == [
        "system prompt",
        "new question",
    ]
    restore_audit = execution.state["stage_summaries"]["checkpoint_restore"]
    assert restore_audit["checkpoint_restore_applied"] is False
    assert restore_audit["checkpoint_restore_schema_supported"] is False
    assert set(restore_audit["checkpoint_restore_reset_fields"]) >= {
        "messages",
        "preprocess_next",
        "reflection",
        "user_input",
    }
    assert "memory_keys" not in execution.state
    assert "runtime_config" not in execution.state
    assert execution.run_context["user_id"] == f"anonymous:{session.id}"


@pytest.mark.asyncio
async def test_prepare_kb_chat_execution_uses_checkpoint_messages_for_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(monkeypatch)
    session = SimpleNamespace(
        id=uuid.uuid4(),
        selected_kb_ids=[],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
        kb_chat_config=None,
    )
    run = AgentRun(
        id=uuid.uuid4(),
        run_type=AgentRunType.KB_ANSWER,
        question="original question",
        mode=AgentMode.SINGLE_AGENT,
        status=AgentRunStatus.RUNNING,
    )
    checkpoint_tuple = SimpleNamespace(
        checkpoint={
            "id": "cp-resume",
            "channel_values": {
                "schema_version": STATE_SCHEMA_V3,
                "messages": [
                    SystemMessage(content="system prompt"),
                    HumanMessage(content="original question"),
                    AIMessage(content="请补充目标对象"),
                ],
                "pending_tool_calls": [{"name": "stale"}],
            },
        }
    )
    monkeypatch.setattr(
        kb_chat_service_module.CheckpointManager,
        "get_state",
        AsyncMock(return_value=checkpoint_tuple),
    )

    execution = await service._prepare_kb_chat_execution(
        session=session,
        user_content="目标对象是 A 产品",
        run=run,
    )

    assert [message.content for message in execution.state["messages"]] == [
        "system prompt",
        "original question",
        "请补充目标对象",
        "目标对象是 A 产品",
    ]
    restore_audit = execution.state["stage_summaries"]["checkpoint_restore"]
    assert restore_audit["checkpoint_restore_applied"] is True
    assert restore_audit["checkpoint_restore_schema_supported"] is True
    assert "pending_tool_calls" in restore_audit["checkpoint_restore_reset_fields"]


@pytest.mark.asyncio
async def test_prepare_kb_chat_execution_rejects_resume_from_unsupported_checkpoint_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(monkeypatch)
    session = SimpleNamespace(
        id=uuid.uuid4(),
        selected_kb_ids=[],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
        kb_chat_config=None,
    )
    run = AgentRun(
        id=uuid.uuid4(),
        run_type=AgentRunType.KB_ANSWER,
        question="original question",
        mode=AgentMode.SINGLE_AGENT,
        status=AgentRunStatus.RUNNING,
    )
    checkpoint_tuple = SimpleNamespace(
        checkpoint={
            "id": "cp-unsupported",
            "channel_values": {
                "schema_version": "kb_chat_state_v999",
                "messages": [
                    SystemMessage(content="system prompt"),
                    HumanMessage(content="original question"),
                    AIMessage(content="请补充目标对象"),
                ],
            },
        }
    )
    monkeypatch.setattr(
        kb_chat_service_module.CheckpointManager,
        "get_state",
        AsyncMock(return_value=checkpoint_tuple),
    )

    execution = await service._prepare_kb_chat_execution(
        session=session,
        user_content="目标对象是 A 产品",
        run=run,
    )

    assert [message.content for message in execution.state["messages"]] == [
        "system prompt",
        "目标对象是 A 产品",
    ]
    restore_audit = execution.state["stage_summaries"]["checkpoint_restore"]
    assert restore_audit["checkpoint_restore_applied"] is False
    assert restore_audit["checkpoint_restore_schema_supported"] is False
    assert "schema_version" in restore_audit["checkpoint_restore_legacy_fields"]

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.services.general_chat_service as general_chat_service_module
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_session import AgentMode, ChatSessionType
from app.schemas.chats import ToolApprovalRequest
from app.services.chat_replay_policy import ReplayDecision, ReplayMode
from app.services.general_chat_service import GeneralChatService


async def _collect_events(stream) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    async for event_name, payload in stream:
        events.append((event_name, payload))
    return events


class _FakeDb:
    def __init__(self) -> None:
        self._tracked: list[object] = []

    def add(self, obj: object) -> None:
        self._tracked.append(obj)

    async def flush(self) -> None:
        self._ensure_defaults()

    async def commit(self) -> None:
        self._ensure_defaults()

    async def rollback(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        self._ensure_defaults(obj)

    def _ensure_defaults(self, target: object | None = None) -> None:
        now = datetime.now(timezone.utc)
        tracked = [target] if target is not None else list(self._tracked)
        for obj in tracked:
            if obj is None:
                continue
            if getattr(obj, "id", None) is None:
                setattr(obj, "id", uuid.uuid4())
            if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
                setattr(obj, "created_at", now)


class _FakePromptLoader:
    def render_with_few_shot(self, _: str) -> str:
        return "system"


class _FakeAgent:
    def __init__(self, *, tool_name: str) -> None:
        self._tool_name = tool_name

    async def astream(self, *_args, **_kwargs):
        token = SimpleNamespace(
            type="ai",
            tool_call_chunks=[
                {
                    "id": "call-1",
                    "name": self._tool_name,
                    "args": {"query": "LangChain MCP quickstart"},
                }
            ],
            tool_calls=None,
            content=None,
            content_blocks=None,
        )
        yield "messages", (token, {"langgraph_node": "model"})


class _FakeResumeAgent:
    async def ainvoke(self, *_args, **_kwargs):
        return {"messages": [general_chat_service_module.AIMessage(content="resume ok")]}


def _make_pending_writes(*, interrupt_id: str, tool_name: str) -> list[tuple[None, str, dict]]:
    return [
        (
            None,
            "__interrupt__",
            {
                "id": interrupt_id,
                "value": {
                    "action_requests": [
                        {
                            "name": tool_name,
                            "args": {"query": "LangChain MCP quickstart"},
                            "description": "外部工具调用待审批",
                        }
                    ]
                },
            },
        )
    ]


def _build_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    checkpoint_states: list[object | None],
) -> tuple[GeneralChatService, str]:
    service = GeneralChatService.__new__(GeneralChatService)
    service._db = _FakeDb()
    service._llm = None
    service._settings = SimpleNamespace(mcp_enabled=True, web_search_api_key=None)
    service._prompts = _FakePromptLoader()
    service._redis = None
    service._http_client = None
    service._dedup_missing_table_warned = False
    service._build_context_metrics = lambda messages: {"messages": len(messages)}
    service._build_summary_trigger = lambda: ("fraction", 0.7)
    service._resolve_replay_decision = lambda: ReplayDecision(
        mode=ReplayMode.MANUAL,
        use_previous_response_id=False,
        require_assistant_response_id=False,
        allow_recovery=False,
    )
    service._build_replay_metrics = lambda *args, **kwargs: {}

    async def _ensure_no_running_general_run(*, session_id: uuid.UUID) -> None:
        assert isinstance(session_id, uuid.UUID)

    async def _load_history(session_id: uuid.UUID, *, limit: int | None = None) -> list[object]:
        assert isinstance(session_id, uuid.UUID)
        assert limit is None
        return []

    tool_name = "mcp__ext-1__search_docs_by_lang_chain"
    tool_meta_by_name = {
        tool_name: SimpleNamespace(
            extension_id="ext-1",
            extension_name="LangChain 文档",
            raw_tool_name="search_docs_by_lang_chain",
            is_builtin=False,
        )
    }

    async def _load_tool_registry_for_session(*, session: object) -> tuple[list[object], dict[str, object]]:
        assert session is not None
        return [], tool_meta_by_name

    @asynccontextmanager
    async def _load_runtime_tool_registry_for_session(*, session: object):
        assert session is not None
        yield [], tool_meta_by_name

    service._ensure_no_running_general_run = _ensure_no_running_general_run
    service._load_history = _load_history
    service._load_tool_registry_for_session = _load_tool_registry_for_session
    service._load_runtime_tool_registry_for_session = (
        _load_runtime_tool_registry_for_session
    )

    monkeypatch.setattr(
        general_chat_service_module,
        "create_chat_model",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        general_chat_service_module,
        "build_general_chat_agent",
        lambda **_kwargs: _FakeAgent(tool_name=tool_name),
    )
    monkeypatch.setattr(
        general_chat_service_module.CheckpointManager,
        "make_config",
        lambda _thread_id: {},
    )

    states = list(checkpoint_states)

    async def _get_state(_thread_id: str):
        return states.pop(0) if states else None

    monkeypatch.setattr(
        general_chat_service_module.CheckpointManager,
        "get_state",
        _get_state,
    )

    return service, tool_name


@pytest.mark.asyncio
async def test_answer_stream_emits_interrupt_when_checkpoint_contains_pending_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid.UUID("00000000-0000-0000-0000-000000000101")
    tool_name = "mcp__ext-1__search_docs_by_lang_chain"
    service, tool_name = _build_service(
        monkeypatch,
        checkpoint_states=[
            None,
            SimpleNamespace(
                checkpoint={"channel_values": {"messages": []}},
                pending_writes=_make_pending_writes(
                    interrupt_id="interrupt-1",
                    tool_name=tool_name,
                ),
            ),
        ],
    )

    session = SimpleNamespace(
        id=session_id,
        session_type=ChatSessionType.GENERAL_CHAT,
        allow_external=True,
        mode=AgentMode.SINGLE_AGENT,
    )

    events = await _collect_events(
        service.answer_stream(
            session=session,
            user_content="请查询 LangChain MCP quickstart",
        )
    )

    assert [event_name for event_name, _ in events] == ["meta", "messages", "interrupt"]
    interrupt_payload = events[-1][1]
    assert interrupt_payload["status"] == "pending_tool_approval"
    assert interrupt_payload["pending_interrupts"][0]["interrupt_id"] == "interrupt-1"
    assert interrupt_payload["pending_interrupts"][0]["pending_tool_calls"] == [
        {
            "extension_id": "ext-1",
            "extension_name": "LangChain 文档",
            "tool_name": "search_docs_by_lang_chain",
            "args": {"query": "LangChain MCP quickstart"},
            "is_builtin": False,
        }
    ]


@pytest.mark.asyncio
async def test_resume_after_tool_approval_stream_emits_followup_interrupt_from_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid.UUID("00000000-0000-0000-0000-000000000201")
    tool_name = "mcp__ext-1__search_docs_by_lang_chain"
    service, tool_name = _build_service(
        monkeypatch,
        checkpoint_states=[
            SimpleNamespace(
                checkpoint={"channel_values": {"messages": []}},
                pending_writes=_make_pending_writes(
                    interrupt_id="interrupt-1",
                    tool_name=tool_name,
                ),
            ),
            SimpleNamespace(
                checkpoint={"channel_values": {"messages": []}},
                pending_writes=_make_pending_writes(
                    interrupt_id="interrupt-2",
                    tool_name=tool_name,
                ),
            ),
        ],
    )

    async def _ensure_resume_target_valid(*, session: object, run: object) -> None:
        assert session is not None
        assert run is not None

    async def _fail_extension_preflight(_pending_interrupts: list[dict]) -> None:
        raise AssertionError("resume stream should not use stateless extension preflight")

    service._ensure_resume_target_valid = _ensure_resume_target_valid
    setattr(service, "_ensure" + "_extensions_connected", _fail_extension_preflight)

    session = SimpleNamespace(
        id=session_id,
        session_type=ChatSessionType.GENERAL_CHAT,
        allow_external=True,
        mode=AgentMode.SINGLE_AGENT,
    )
    run = AgentRun(
        id=uuid.UUID("00000000-0000-0000-0000-000000000202"),
        run_type=AgentRunType.GENERAL_ANSWER,
        session_id=session_id,
        question="请查询 LangChain MCP quickstart",
        selected_kb_ids=None,
        allow_external=True,
        mode=AgentMode.SINGLE_AGENT,
        status=AgentRunStatus.RUNNING,
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
    )
    approval = ToolApprovalRequest.model_validate(
        {
            "interrupts": [
                {
                    "interrupt_id": "interrupt-1",
                    "decisions": [{"type": "approve"}],
                }
            ]
        }
    )

    events = await _collect_events(
        service.resume_after_tool_approval_stream(
            session=session,
            run=run,
            approval=approval,
        )
    )

    assert [event_name for event_name, _ in events] == ["meta", "messages", "interrupt"]
    interrupt_payload = events[-1][1]
    assert interrupt_payload["status"] == "pending_tool_approval"
    assert interrupt_payload["pending_interrupts"][0]["interrupt_id"] == "interrupt-2"


@pytest.mark.asyncio
async def test_resume_after_tool_approval_skips_stateless_extension_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid.UUID("00000000-0000-0000-0000-000000000211")
    tool_name = "mcp__ext-1__search_docs_by_lang_chain"
    service, _ = _build_service(
        monkeypatch,
        checkpoint_states=[
            SimpleNamespace(
                checkpoint={"channel_values": {"messages": []}},
                pending_writes=_make_pending_writes(
                    interrupt_id="interrupt-1",
                    tool_name=tool_name,
                ),
            ),
        ],
    )

    async def _ensure_resume_target_valid(*, session: object, run: object) -> None:
        assert session is not None
        assert run is not None

    async def _fail_extension_preflight(_pending_interrupts: list[dict]) -> None:
        raise AssertionError("resume should not use stateless extension preflight")

    service._ensure_resume_target_valid = _ensure_resume_target_valid
    setattr(service, "_ensure" + "_extensions_connected", _fail_extension_preflight)

    monkeypatch.setattr(
        general_chat_service_module,
        "create_chat_model",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        general_chat_service_module,
        "build_general_chat_agent",
        lambda **_kwargs: _FakeResumeAgent(),
    )
    monkeypatch.setattr(
        general_chat_service_module.CheckpointManager,
        "make_config",
        lambda _thread_id: {},
    )

    session = SimpleNamespace(
        id=session_id,
        session_type=ChatSessionType.GENERAL_CHAT,
        allow_external=True,
        mode=AgentMode.SINGLE_AGENT,
    )
    run = AgentRun(
        id=uuid.UUID("00000000-0000-0000-0000-000000000212"),
        run_type=AgentRunType.GENERAL_ANSWER,
        session_id=session_id,
        question="请查询 LangChain MCP quickstart",
        selected_kb_ids=None,
        allow_external=True,
        mode=AgentMode.SINGLE_AGENT,
        status=AgentRunStatus.RUNNING,
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
    )
    approval = ToolApprovalRequest.model_validate(
        {
            "interrupts": [
                {
                    "interrupt_id": "interrupt-1",
                    "decisions": [{"type": "approve"}],
                }
            ]
        }
    )

    result = await service.resume_after_tool_approval(
        session=session,
        run=run,
        approval=approval,
    )

    assert result.status == "succeeded"
    assert result.assistant_message.content == "resume ok"


@pytest.mark.asyncio
async def test_answer_stream_prefers_runtime_tool_registry_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid.UUID("00000000-0000-0000-0000-000000000301")
    service = GeneralChatService.__new__(GeneralChatService)
    service._db = _FakeDb()
    service._llm = None
    service._settings = SimpleNamespace(mcp_enabled=True, web_search_api_key=None)
    service._prompts = _FakePromptLoader()
    service._redis = None
    service._http_client = None
    service._dedup_missing_table_warned = False
    service._build_context_metrics = lambda messages: {"messages": len(messages)}
    service._build_summary_trigger = lambda: ("fraction", 0.7)
    service._resolve_replay_decision = lambda: ReplayDecision(
        mode=ReplayMode.MANUAL,
        use_previous_response_id=False,
        require_assistant_response_id=False,
        allow_recovery=False,
    )
    service._build_replay_metrics = lambda *args, **kwargs: {}

    async def _ensure_no_running_general_run(*, session_id: uuid.UUID) -> None:
        assert isinstance(session_id, uuid.UUID)

    async def _load_history(session_id: uuid.UUID, *, limit: int | None = None) -> list[object]:
        assert isinstance(session_id, uuid.UUID)
        assert limit is None
        return []

    service._ensure_no_running_general_run = _ensure_no_running_general_run
    service._load_history = _load_history

    async def _legacy_loader(*, session: object) -> tuple[list[object], dict[str, object]]:
        raise AssertionError("legacy stateless loader should not be used by answer_stream")

    runtime_entered = False

    @asynccontextmanager
    async def _runtime_loader(*, session: object):
        nonlocal runtime_entered
        assert session is not None
        runtime_entered = True
        yield [], {}

    service._load_tool_registry_for_session = _legacy_loader
    service._load_runtime_tool_registry_for_session = _runtime_loader

    monkeypatch.setattr(
        general_chat_service_module,
        "create_chat_model",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        general_chat_service_module,
        "build_general_chat_agent",
        lambda **_kwargs: _FakeAgent(tool_name="mcp__ext-1__search_docs_by_lang_chain"),
    )
    monkeypatch.setattr(
        general_chat_service_module.CheckpointManager,
        "make_config",
        lambda _thread_id: {},
    )

    async def _get_state(_thread_id: str):
        return None

    monkeypatch.setattr(
        general_chat_service_module.CheckpointManager,
        "get_state",
        _get_state,
    )

    session = SimpleNamespace(
        id=session_id,
        session_type=ChatSessionType.GENERAL_CHAT,
        allow_external=True,
        mode=AgentMode.SINGLE_AGENT,
    )

    events = await _collect_events(
        service.answer_stream(
            session=session,
            user_content="请查询 LangChain MCP quickstart",
        )
    )

    assert runtime_entered is True
    assert events[:2] == [
        (
            "meta",
            {
                "run_id": events[0][1]["run_id"],
                "session_id": str(session_id),
                "session_type": "general_chat",
                "thread_id": str(session_id),
                "mode": "single_agent",
            },
        ),
        (
            "messages",
            {
                "run_id": events[1][1]["run_id"],
                "node": "model",
                "deltas": events[1][1]["deltas"],
                "ts": events[1][1]["ts"],
            },
        ),
    ]

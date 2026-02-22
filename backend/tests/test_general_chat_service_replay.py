from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.messages import AIMessage

from app.core.errors import AppError
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.models.chat_session import AgentMode
from app.services.chat_replay_policy import ReplayDecision, ReplayMode
from app.services.general_chat_service import GeneralChatService


def test_sanitize_history_for_replay_drops_assistant_without_response_id() -> None:
    service = GeneralChatService(db=MagicMock(), llm=MagicMock())
    history = [
        LLMMessage(role="user", content="你好"),
        LLMMessage(role="assistant", content="你好！"),
        LLMMessage(role="assistant", content="继续", response_id="resp_123"),
    ]

    sanitized = service._sanitize_history_for_replay(
        history, require_assistant_response_id=True
    )

    assert [msg.content for msg in sanitized] == ["你好", "继续"]


def test_to_langchain_message_sets_response_metadata_id() -> None:
    message = LLMMessage(role="assistant", content="ok", response_id="resp_123")
    ai = GeneralChatService._to_langchain_message(message)
    assert isinstance(ai, AIMessage)
    assert ai.response_metadata.get("id") == "resp_123"


class _DummyDB:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None

    async def execute(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("execute should not be called in this test")


class _FailingAgent:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def ainvoke(self, *_args: object, **_kwargs: object) -> dict:
        raise self._exc


class _SucceedingAgent:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def ainvoke(self, *_args: object, **_kwargs: object) -> dict:
        return self._payload


class _FakeOpenAINotFoundError(Exception):
    __module__ = "openai"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.status_code = 404
        self.body = {"error": {"message": message}}


@pytest.mark.asyncio
async def test_answer_auto_recovers_when_previous_response_id_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _DummyDB()
    service = GeneralChatService(db=db, llm=MagicMock())
    session = SimpleNamespace(
        id=uuid.uuid4(),
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
    )

    replay_decision = ReplayDecision(
        mode=ReplayMode.RESPONSE_ID,
        use_previous_response_id=True,
        require_assistant_response_id=True,
        allow_recovery=True,
    )
    monkeypatch.setattr(
        service,
        "_ensure_no_running_general_run",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(service, "_resolve_replay_decision", lambda: replay_decision)
    monkeypatch.setattr(service, "_load_history", AsyncMock(return_value=[]))

    result_payload = {"messages": [AIMessage(content="ok", response_metadata={"id": "resp_ok"})]}
    agents: list[object] = [
        _FailingAgent(
            _FakeOpenAINotFoundError("Response with id 'resp_missing' not found.")
        ),
        _SucceedingAgent(result_payload),
    ]
    monkeypatch.setattr(
        "app.services.general_chat_service.build_tool_registry",
        AsyncMock(return_value=([], {})),
    )
    monkeypatch.setattr(
        "app.services.general_chat_service.create_chat_model",
        MagicMock(side_effect=["model-first", "model-second"]),
    )
    monkeypatch.setattr(
        "app.services.general_chat_service.build_general_chat_agent",
        MagicMock(side_effect=agents),
    )
    monkeypatch.setattr(
        "app.services.general_chat_service.CheckpointManager.get_state",
        AsyncMock(return_value=None),
    )
    delete_thread = AsyncMock()
    monkeypatch.setattr(
        "app.services.general_chat_service.CheckpointManager.delete_thread",
        delete_thread,
    )
    monkeypatch.setattr(
        "app.services.general_chat_service.CheckpointManager.make_config",
        MagicMock(return_value={"configurable": {"thread_id": str(session.id)}}),
    )
    sentinel = object()
    finalize = AsyncMock(return_value=sentinel)
    monkeypatch.setattr(service, "_finalize_run", finalize)

    result = await service.answer(session=session, user_content="hello")
    assert result is sentinel
    delete_thread.assert_awaited_once()
    assert finalize.await_args.kwargs["replay_metrics"]["replay"]["recovered"] is True


@pytest.mark.asyncio
async def test_answer_strict_mode_raises_when_previous_response_id_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _DummyDB()
    service = GeneralChatService(db=db, llm=MagicMock())
    session = SimpleNamespace(
        id=uuid.uuid4(),
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
    )

    replay_decision = ReplayDecision(
        mode=ReplayMode.RESPONSE_ID,
        use_previous_response_id=True,
        require_assistant_response_id=True,
        allow_recovery=False,
    )
    monkeypatch.setattr(
        service,
        "_ensure_no_running_general_run",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(service, "_resolve_replay_decision", lambda: replay_decision)
    monkeypatch.setattr(service, "_load_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "app.services.general_chat_service.build_tool_registry",
        AsyncMock(return_value=([], {})),
    )
    monkeypatch.setattr(
        "app.services.general_chat_service.create_chat_model",
        MagicMock(return_value="model"),
    )
    monkeypatch.setattr(
        "app.services.general_chat_service.build_general_chat_agent",
        MagicMock(
            return_value=_FailingAgent(
                _FakeOpenAINotFoundError("Response with id 'resp_missing' not found.")
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.general_chat_service.CheckpointManager.get_state",
        AsyncMock(return_value=None),
    )
    delete_thread = AsyncMock()
    monkeypatch.setattr(
        "app.services.general_chat_service.CheckpointManager.delete_thread",
        delete_thread,
    )
    monkeypatch.setattr(
        "app.services.general_chat_service.CheckpointManager.make_config",
        MagicMock(return_value={"configurable": {"thread_id": str(session.id)}}),
    )

    with pytest.raises(AppError) as exc:
        await service.answer(session=session, user_content="hello")
    assert exc.value.code == "CHAT_REPLAY_STATE_EXPIRED"
    delete_thread.assert_not_awaited()

from __future__ import annotations

import asyncio
import inspect
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.sse import SseHeartbeatStats
from app.api.v1.endpoints import chats
from app.core.errors import AppError, not_found
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_session import AgentMode, ChatSession, ChatSessionType
from app.schemas.chats import (
    ClarificationResumeRequest,
    InterruptDecisionBatch,
    ToolApprovalRequest,
    ToolDecision,
)
from app.services import kb_chat_service as kb_chat_service_module
from app.services.kb_chat_service import KbChatService


class _FakeLookupDb:
    def __init__(self, *, session: ChatSession | None = None) -> None:
        self._session = session

    async def get(self, model: type[Any], object_id: uuid.UUID) -> Any:
        del object_id
        if model is chats.ChatSession:
            return self._session
        raise AssertionError(f"unexpected lookup: {model!r}")


class _NeverEndingStream:
    def __init__(self) -> None:
        self.closed = False

    def __aiter__(self) -> _NeverEndingStream:
        return self

    async def __anext__(self) -> Any:
        await asyncio.sleep(3600)
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


class _CompiledGraph:
    def __init__(self, stream: _NeverEndingStream) -> None:
        self._stream = stream

    def astream(self, *args: Any, **kwargs: Any) -> _NeverEndingStream:
        del args, kwargs
        return self._stream


class _DisconnectedRequest:
    async def is_disconnected(self) -> bool:
        return True


def _build_general_session() -> ChatSession:
    return ChatSession(
        id=uuid.uuid4(),
        session_type=ChatSessionType.GENERAL_CHAT,
        selected_kb_ids=None,
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
    )


def _build_kb_session() -> ChatSession:
    return ChatSession(
        id=uuid.uuid4(),
        session_type=ChatSessionType.KB_CHAT,
        selected_kb_ids=None,
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
    )


def _build_run(
    *,
    session_id: uuid.UUID,
    run_type: AgentRunType,
) -> AgentRun:
    return AgentRun(
        id=uuid.uuid4(),
        run_type=run_type,
        session_id=session_id,
        question="question",
        selected_kb_ids=None,
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
        status=AgentRunStatus.RUNNING,
    )


def _build_tool_approval_request() -> ToolApprovalRequest:
    return ToolApprovalRequest(
        interrupts=[
            InterruptDecisionBatch(
                interrupt_id="interrupt-1",
                decisions=[ToolDecision(type="approve")],
            )
        ]
    )


def test_stream_routes_do_not_depend_on_request_scoped_db() -> None:
    assert "db" not in inspect.signature(chats.create_chat_message_stream).parameters
    assert (
        "db"
        not in inspect.signature(
            chats.resume_kb_chat_after_clarification_stream
        ).parameters
    )
    assert "db" not in inspect.signature(chats.resume_general_chat_stream).parameters


def test_general_chat_resume_events_raise_http_error_before_sse_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _exercise() -> None:
        @asynccontextmanager
        async def fake_scope(*, resources: object) -> Any:
            del resources
            yield _FakeLookupDb(session=None), SimpleNamespace()

        monkeypatch.setattr(chats, "open_general_chat_service_scope", fake_scope)

        with pytest.raises(AppError) as exc_info:
            await chats._prime_stream_events(
                chats._stream_general_chat_resume_events(
                    resources=SimpleNamespace(),
                    session_id=uuid.uuid4(),
                    run_id=uuid.uuid4(),
                    approval=_build_tool_approval_request(),
                    request=SimpleNamespace(),
                )
            )

        assert exc_info.value.code == "CHAT_SESSION_NOT_FOUND"
        assert exc_info.value.status_code == 404

    asyncio.run(_exercise())


def test_kb_chat_resume_events_raise_http_error_before_sse_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _exercise() -> None:
        @asynccontextmanager
        async def fake_scope(*, resources: object) -> Any:
            del resources
            yield _FakeLookupDb(session=None), SimpleNamespace()

        monkeypatch.setattr(chats, "open_kb_chat_service_scope", fake_scope)

        with pytest.raises(AppError) as exc_info:
            await chats._prime_stream_events(
                chats._stream_kb_chat_resume_events(
                    resources=SimpleNamespace(),
                    session_id=uuid.uuid4(),
                    run_id=uuid.uuid4(),
                    user_content="clarify",
                    request=SimpleNamespace(),
                    heartbeat_stats=SseHeartbeatStats(),
                )
            )

        assert exc_info.value.code == "CHAT_SESSION_NOT_FOUND"
        assert exc_info.value.status_code == 404

    asyncio.run(_exercise())


def test_resume_general_chat_stream_primes_events_before_returning_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _exercise() -> None:
        session = _build_general_session()
        run = _build_run(
            session_id=session.id,
            run_type=AgentRunType.GENERAL_ANSWER,
        )

        async def raising_events(**kwargs: Any) -> Any:
            del kwargs
            raise not_found("运行记录不存在", code="CHAT_RUN_NOT_FOUND")
            if False:
                yield ("", None)

        monkeypatch.setattr(chats, "_stream_general_chat_resume_events", raising_events)

        with pytest.raises(AppError) as exc_info:
            await chats.resume_general_chat_stream(
                request=SimpleNamespace(),
                resources=SimpleNamespace(),
                session_id=session.id,
                run_id=run.id,
                body=_build_tool_approval_request(),
            )

        assert exc_info.value.code == "CHAT_RUN_NOT_FOUND"
        assert exc_info.value.status_code == 404

    asyncio.run(_exercise())


def test_resume_kb_chat_stream_primes_events_before_returning_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _exercise() -> None:
        session = _build_kb_session()
        run = _build_run(
            session_id=session.id,
            run_type=AgentRunType.KB_ANSWER,
        )
        run.metrics = {"clarification_pending": True}

        async def raising_events(**kwargs: Any) -> Any:
            del kwargs
            raise not_found("运行记录不存在", code="CHAT_RUN_NOT_FOUND")
            if False:
                yield ("", None)

        monkeypatch.setattr(chats, "_stream_kb_chat_resume_events", raising_events)

        with pytest.raises(AppError) as exc_info:
            await chats.resume_kb_chat_after_clarification_stream(
                request=SimpleNamespace(),
                resources=SimpleNamespace(),
                session_id=session.id,
                run_id=run.id,
                body=ClarificationResumeRequest(content="clarify"),
            )

        assert exc_info.value.code == "CHAT_RUN_NOT_FOUND"
        assert exc_info.value.status_code == 404

    asyncio.run(_exercise())


def test_kb_chat_disconnect_marks_run_canceled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _exercise() -> None:
        service = object.__new__(KbChatService)
        stream = _NeverEndingStream()
        session = _build_kb_session()
        run = _build_run(
            session_id=session.id,
            run_type=AgentRunType.KB_ANSWER,
        )
        persisted: list[dict[str, Any]] = []
        released: list[object] = []
        exec_ctx = SimpleNamespace(
            run=run,
            thread_id="thread-1",
            compiled_graph=_CompiledGraph(stream),
            graph=SimpleNamespace(make_run_config=lambda **kwargs: {}),
            state={
                "messages": [],
                "pending_tool_calls": [],
                "stage_summaries": {},
                "metrics": {},
                "loop_counts": {},
            },
            run_context=None,
            resume_checkpoint_id=None,
        )

        def build_protocol_event_payload(
            *,
            event_type: str,
            run_id: uuid.UUID,
            payload: dict[str, Any],
            **_: Any,
        ) -> dict[str, Any]:
            return {
                "event_type": event_type,
                "run_id": str(run_id),
                **payload,
            }

        def build_stream_state_payload(**kwargs: Any) -> dict[str, Any]:
            run_status = kwargs["run_status"]
            current_step_status = kwargs.get("current_step_status_override") or run_status
            return {
                "run_status": run_status,
                "current_step_status": current_step_status,
                "message": kwargs.get("message"),
            }

        async def persist_guardrail_run(**kwargs: Any) -> None:
            persisted.append(
                {
                    "status": kwargs["status"],
                    "reason": kwargs["reason"],
                }
            )

        async def fake_cached_stream_events(
            self: Any,
            *,
            session: ChatSession,
            user_content: str,
        ) -> None:
            del self, session, user_content
            return None

        async def fake_prepare_execution(
            self: Any,
            *,
            session: ChatSession,
            user_content: str,
            run: AgentRun | None,
        ) -> Any:
            del self, session, user_content, run
            return exec_ctx

        service._build_protocol_event_payload = build_protocol_event_payload
        service._build_stream_state_payload = build_stream_state_payload
        service._build_active_path = lambda **kwargs: []
        service._build_scoped_node_path = lambda **kwargs: []
        service._build_graph_stream_options = lambda: {}
        service._normalize_graph_stream_event = lambda raw_event: raw_event
        service._persist_guardrail_run = persist_guardrail_run
        service._release_retrieval_buffer = lambda value: released.append(value)

        monkeypatch.setattr(
            kb_chat_service_module.kb_cached,
            "_maybe_build_cached_stream_events",
            fake_cached_stream_events,
        )
        monkeypatch.setattr(
            kb_chat_service_module.kb_execution,
            "_prepare_kb_chat_execution",
            fake_prepare_execution,
        )
        monkeypatch.setattr(
            kb_chat_service_module,
            "build_graph_input_state",
            lambda state: state,
        )

        emitted_events: list[tuple[str, Any]] = []
        async for item in service.answer_stream(
            session=session,
            user_content="hello",
            request=_DisconnectedRequest(),
        ):
            emitted_events.append(item)

        assert persisted == [
            {
                "status": AgentRunStatus.CANCELED,
                "reason": "errterm_client_disconnect",
            }
        ]
        canceled_state = next(
            payload
            for event_name, payload in emitted_events
            if event_name == "state"
            and payload.get("message") == "client disconnected before stream completed"
        )
        assert canceled_state["run_status"] == AgentRunStatus.CANCELED.value
        assert canceled_state["current_step_status"] == AgentRunStatus.CANCELED.value
        assert released == [exec_ctx]
        assert stream.closed is True

    asyncio.run(_exercise())

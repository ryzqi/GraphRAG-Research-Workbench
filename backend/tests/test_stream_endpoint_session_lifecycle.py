from __future__ import annotations
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.app_resources import get_app_resources
from app.api.dependencies import services as service_deps
from app.api.v1.endpoints import chats as chats_endpoint
from app.api.v1.endpoints import ingestion_batches as ingestion_endpoint
from app.api.v1.endpoints import research as research_endpoint
from app.db.session import get_db_session
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_session import AgentMode, ChatSession, ChatSessionType


class _FakeDb:
    def __init__(
        self,
        *,
        session: object | None = None,
        run: object | None = None,
    ) -> None:
        self._session = session
        self._run = run

    async def get(self, model: object, key: object) -> object | None:
        if model is ChatSession and getattr(self._session, "id", None) == key:
            return self._session
        if model is AgentRun and getattr(self._run, "id", None) == key:
            return self._run
        return None


class _PoisonGeneralChatService:
    def answer_stream(self, **_: Any):
        raise AssertionError("流式创建不应继续使用请求期 GeneralChatService")

    def resume_after_tool_approval_stream(self, **_: Any):
        raise AssertionError("流式恢复不应继续使用请求期 GeneralChatService")


class _PoisonKbChatService:
    async def answer_stream(self, **_: Any):
        raise AssertionError("流式创建/恢复不应继续使用请求期 KbChatService")
        yield ("meta", {})


class _FreshGeneralChatService:
    def __init__(
        self,
        *,
        expected_session: object,
        expected_run: object | None = None,
        marker: str,
    ) -> None:
        self._expected_session = expected_session
        self._expected_run = expected_run
        self._marker = marker

    def answer_stream(self, *, session: object, **_: Any):
        assert session is self._expected_session

        async def _events():
            yield ("meta", {"marker": self._marker})

        return _events()

    def resume_after_tool_approval_stream(
        self,
        *,
        session: object,
        run: object,
        **_: Any,
    ):
        assert session is self._expected_session
        assert run is self._expected_run

        async def _events():
            yield ("meta", {"marker": self._marker})

        return _events()


class _FreshKbChatService:
    def __init__(
        self,
        *,
        expected_session: object,
        expected_run: object | None = None,
        marker: str,
    ) -> None:
        self._expected_session = expected_session
        self._expected_run = expected_run
        self._marker = marker

    async def answer_stream(
        self,
        *,
        session: object,
        run: object | None = None,
        **_: Any,
    ):
        assert session is self._expected_session
        assert run is self._expected_run
        yield ("meta", {"marker": self._marker})


class _PreflightIngestionService:
    def __init__(self) -> None:
        self.closed = False

    async def get_batch(self, *, batch_id: uuid.UUID):
        return {"batch_id": str(batch_id)}

    async def stream_batch_updates(self, *, batch_id: uuid.UUID):
        if self.closed:
            raise AssertionError("stream_batch_updates 不应复用请求期 IngestionBatchService")
        yield ("update", {"batch_id": str(batch_id), "marker": "request-scope"})


class _FreshIngestionService:
    async def stream_batch_updates(self, *, batch_id: uuid.UUID):
        yield ("update", {"batch_id": str(batch_id), "marker": "fresh-scope"})


class _FakeEnvelope:
    def __init__(self, *, marker: str) -> None:
        self._marker = marker

    def model_dump(self, mode: str = "json") -> dict[str, str]:
        assert mode == "json"
        return {"marker": self._marker}


class _ResearchServiceWithLateFailure:
    def __init__(self) -> None:
        self.closed = False

    async def get_session(self, session_id: uuid.UUID) -> object:
        return SimpleNamespace(id=session_id)

    def list_event_envelopes(self, session: object, *, after_event_id: str | None = None):
        if self.closed:
            raise AssertionError("research 流式响应不应在返回后再读取请求期 service")
        return [_FakeEnvelope(marker="fresh-research")]


def _build_app(*, router, prefix: str) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    return app


def _collect_stream_text(response) -> str:
    return "".join(response.iter_text())


def _override_db(fake_db: _FakeDb):
    async def _dependency():
        yield fake_db

    return _dependency


def _override_value(value: object):
    async def _dependency():
        yield value

    return _dependency


def _build_session(
    *,
    session_id: uuid.UUID,
    session_type: ChatSessionType,
) -> object:
    return SimpleNamespace(
        id=session_id,
        session_type=session_type,
        mode=AgentMode.SINGLE_AGENT,
        allow_external=False,
        selected_kb_ids=[uuid.uuid4()] if session_type == ChatSessionType.KB_CHAT else None,
    )


def _build_run(
    *,
    run_id: uuid.UUID,
    session_id: uuid.UUID,
    run_type: AgentRunType,
    metrics: dict[str, object] | None = None,
) -> object:
    return SimpleNamespace(
        id=run_id,
        session_id=session_id,
        run_type=run_type,
        status=AgentRunStatus.RUNNING,
        metrics=metrics or {},
    )


@pytest.mark.parametrize(
    ("session_type", "path_suffix", "scope_name", "open_attr", "service_override"),
    [
        (
            ChatSessionType.GENERAL_CHAT,
            "messages/stream",
            "fresh-general-create",
            "open_general_chat_service_scope",
            service_deps.build_general_chat_service,
        ),
        (
            ChatSessionType.KB_CHAT,
            "messages/stream",
            "fresh-kb-create",
            "open_kb_chat_service_scope",
            service_deps.build_kb_chat_service,
        ),
    ],
)
def test_create_chat_message_stream_uses_fresh_service_scope(
    monkeypatch: pytest.MonkeyPatch,
    session_type: ChatSessionType,
    path_suffix: str,
    scope_name: str,
    open_attr: str,
    service_override: object,
) -> None:
    session_id = uuid.uuid4()
    preflight_session = _build_session(session_id=session_id, session_type=session_type)
    fake_db = _FakeDb(session=preflight_session)

    app = _build_app(router=chats_endpoint.router, prefix="/chats")
    app.dependency_overrides[get_db_session] = _override_db(fake_db)
    app.dependency_overrides[get_app_resources] = lambda: object()
    app.dependency_overrides[service_deps.build_general_chat_service] = _override_value(
        _PoisonGeneralChatService()
    )
    app.dependency_overrides[service_deps.build_kb_chat_service] = _override_value(
        _PoisonKbChatService()
    )

    if session_type == ChatSessionType.GENERAL_CHAT:
        fresh_service = _FreshGeneralChatService(
            expected_session=preflight_session,
            marker=scope_name,
        )
    else:
        fresh_service = _FreshKbChatService(
            expected_session=preflight_session,
            marker=scope_name,
        )

    @asynccontextmanager
    async def _open_scope(*, resources: object):
        yield _FakeDb(), fresh_service

    monkeypatch.setattr(chats_endpoint, open_attr, _open_scope)

    with TestClient(app) as client:
        with client.stream(
            "POST",
            f"/chats/{session_id}/{path_suffix}",
            json={"content": "hello"},
        ) as response:
            payload = _collect_stream_text(response)

    assert response.status_code == 200
    assert f'"marker":"{scope_name}"' in payload


def test_resume_general_chat_stream_reloads_targets_in_fresh_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid.uuid4()
    run_id = uuid.uuid4()
    preflight_session = _build_session(
        session_id=session_id,
        session_type=ChatSessionType.GENERAL_CHAT,
    )
    preflight_run = _build_run(
        run_id=run_id,
        session_id=session_id,
        run_type=AgentRunType.GENERAL_ANSWER,
    )
    fresh_session = _build_session(
        session_id=session_id,
        session_type=ChatSessionType.GENERAL_CHAT,
    )
    fresh_run = _build_run(
        run_id=run_id,
        session_id=session_id,
        run_type=AgentRunType.GENERAL_ANSWER,
    )

    app = _build_app(router=chats_endpoint.router, prefix="/chats")
    app.dependency_overrides[get_db_session] = _override_db(
        _FakeDb(session=preflight_session, run=preflight_run)
    )
    app.dependency_overrides[get_app_resources] = lambda: object()
    app.dependency_overrides[service_deps.build_general_chat_service] = _override_value(
        _PoisonGeneralChatService()
    )

    fresh_service = _FreshGeneralChatService(
        expected_session=fresh_session,
        expected_run=fresh_run,
        marker="fresh-general-resume",
    )

    @asynccontextmanager
    async def _open_scope(*, resources: object):
        yield _FakeDb(session=fresh_session, run=fresh_run), fresh_service

    monkeypatch.setattr(chats_endpoint, "open_general_chat_service_scope", _open_scope)

    with TestClient(app) as client:
        with client.stream(
            "POST",
            f"/chats/{session_id}/runs/{run_id}/resume/stream",
            json={
                "interrupts": [
                    {"interrupt_id": "interrupt-1", "decisions": [{"type": "approve"}]}
                ]
            },
        ) as response:
            payload = _collect_stream_text(response)

    assert response.status_code == 200
    assert '"marker":"fresh-general-resume"' in payload


def test_resume_kb_chat_clarification_stream_reloads_targets_in_fresh_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid.uuid4()
    run_id = uuid.uuid4()
    preflight_session = _build_session(
        session_id=session_id,
        session_type=ChatSessionType.KB_CHAT,
    )
    preflight_run = _build_run(
        run_id=run_id,
        session_id=session_id,
        run_type=AgentRunType.KB_ANSWER,
        metrics={"clarification_pending": True},
    )
    fresh_session = _build_session(
        session_id=session_id,
        session_type=ChatSessionType.KB_CHAT,
    )
    fresh_run = _build_run(
        run_id=run_id,
        session_id=session_id,
        run_type=AgentRunType.KB_ANSWER,
        metrics={"clarification_pending": True},
    )

    app = _build_app(router=chats_endpoint.router, prefix="/chats")
    app.dependency_overrides[get_db_session] = _override_db(
        _FakeDb(session=preflight_session, run=preflight_run)
    )
    app.dependency_overrides[get_app_resources] = lambda: object()
    app.dependency_overrides[service_deps.build_kb_chat_service] = _override_value(
        _PoisonKbChatService()
    )

    fresh_service = _FreshKbChatService(
        expected_session=fresh_session,
        expected_run=fresh_run,
        marker="fresh-kb-clarification",
    )

    @asynccontextmanager
    async def _open_scope(*, resources: object):
        yield _FakeDb(session=fresh_session, run=fresh_run), fresh_service

    monkeypatch.setattr(chats_endpoint, "open_kb_chat_service_scope", _open_scope)

    with TestClient(app) as client:
        with client.stream(
            "POST",
            f"/chats/{session_id}/runs/{run_id}/clarification/stream",
            json={"content": "clarify"},
        ) as response:
            payload = _collect_stream_text(response)

    assert response.status_code == 200
    assert '"marker":"fresh-kb-clarification"' in payload


def test_stream_ingestion_batch_uses_fresh_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch_id = uuid.uuid4()
    request_service = _PreflightIngestionService()

    app = _build_app(router=ingestion_endpoint.router, prefix="/ingestion-batches")
    app.dependency_overrides[service_deps.build_ingestion_batch_service] = _override_value(
        request_service
    )
    app.dependency_overrides[get_app_resources] = lambda: object()

    @asynccontextmanager
    async def _open_scope(*, resources: object):
        yield _FakeDb(), _FreshIngestionService()

    monkeypatch.setattr(
        ingestion_endpoint,
        "open_ingestion_batch_service_scope",
        _open_scope,
    )

    with TestClient(app) as client:
        with client.stream("GET", f"/ingestion-batches/{batch_id}/stream") as response:
            request_service.closed = True
            payload = _collect_stream_text(response)

    assert response.status_code == 200
    assert '"marker":"fresh-scope"' in payload


@pytest.mark.asyncio
async def test_stream_research_session_materializes_events_before_response() -> None:
    session_id = uuid.uuid4()
    service = _ResearchServiceWithLateFailure()
    request = SimpleNamespace(headers={}, is_disconnected=lambda: False)

    response = await research_endpoint.stream_research_session(
        session_id=session_id,
        service=service,
        request=request,
        resume_from_event_id=None,
    )

    service.closed = True

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    payload = "".join(chunks)

    assert '"marker":"fresh-research"' in payload

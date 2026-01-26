import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.services.kb_chat_service as kb_chat_service
from app.core.errors import AppError
from app.models.agent_run import AgentRun
from app.models.chat_session import AgentMode as ModelAgentMode
from app.models.chat_session import ChatSession, ChatSessionType
from app.schemas.chats import (
    AgentMode,
    AgentRunRead,
    AgentRunStatus,
    AgentRunType,
    ChatAnswerResponse,
    ChatMessageRead,
    EvidenceItem,
    EvidenceSourceKind,
    MessageRole,
)
from app.services.kb_chat_service import KbChatService


class _DummyDb:
    def __init__(self) -> None:
        self._added: list[object] = []

    def add(self, obj: object) -> None:
        self._added.append(obj)

    async def flush(self) -> None:
        for obj in self._added:
            if hasattr(obj, "id") and getattr(obj, "id") is None:
                setattr(obj, "id", uuid.uuid4())

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None

    async def execute(self, _stmt: object) -> object:
        class _Result:
            def scalars(self) -> "_Result":
                return self

            def all(self) -> list[object]:
                return []

        return _Result()


class _DummyContextBuilder:
    def build_history_messages(
        self, *, history: list[object], summary_text: str | None
    ) -> tuple[list, dict, dict]:
        return [], {"tokens": 0, "chars": 0, "messages": 0}, {"truncated": False}

    def build_metrics(
        self,
        *,
        history_usage: dict | None = None,
        history_truncation: dict | None = None,
        retrieval_usage: dict | None = None,
        retrieval_truncation: dict | None = None,
    ) -> dict:
        return {
            "history_usage": history_usage or {},
            "history_truncation": history_truncation or {},
            "retrieval_usage": retrieval_usage or {},
            "retrieval_truncation": retrieval_truncation or {},
        }


class _DummySummaryService:
    async def load_latest_summary(self, _session_id: uuid.UUID) -> object | None:
        return None

    def is_summary_message(self, _msg: object) -> bool:
        return False


class _DummyPrompts:
    def render(self, _name: str) -> str:
        return "system"


class _DummyRetrieval:
    last_stats = None
    last_layer_draft = None


class _DummyCheckpoint:
    def __init__(self) -> None:
        self.checkpoint = {"channel_values": {"messages": ["stub"]}}
        self.pending_writes = None


class _DummyGraph:
    def __init__(
        self, *, run_result: dict, stream_chunks: list[tuple[str, object]]
    ) -> None:
        self._run_result = run_result
        self._stream_chunks = stream_chunks

    async def run(self, *_args: object, **_kwargs: object) -> dict:
        return self._run_result

    def compile(self, *_args: object, **_kwargs: object) -> "_DummyGraph":
        return self

    async def astream(self, *_args: object, **_kwargs: object):
        for item in self._stream_chunks:
            yield item


class _DummyChatOpenAI:
    def __init__(self, *args: object, **_kwargs: object) -> None:
        self.args = args


def _build_answer_response() -> ChatAnswerResponse:
    now = datetime.now(timezone.utc)
    assistant = ChatMessageRead(
        id=uuid.uuid4(),
        role=MessageRole.ASSISTANT,
        content="ok",
        created_at=now,
    )
    run = AgentRunRead(
        id=uuid.uuid4(),
        run_type=AgentRunType.KB_ANSWER,
        status=AgentRunStatus.SUCCEEDED,
        mode=AgentMode.SINGLE_AGENT,
        question="q",
        selected_kb_ids=[],
        allow_external=False,
        stage_summaries={},
        metrics={},
        created_at=now,
        started_at=now,
        finished_at=now,
        error_message=None,
    )
    evidence = [
        EvidenceItem(
            source_kind=EvidenceSourceKind.KB,
            kb_id=None,
            material_id=None,
            chunk_id=None,
            locator=None,
            excerpt="",
        )
    ]
    return ChatAnswerResponse(
        assistant_message=assistant,
        evidence=evidence,
        run=run,
    )


def _build_session() -> ChatSession:
    session = ChatSession(
        session_type=ChatSessionType.KB_CHAT,
        selected_kb_ids=[],
        allow_external=False,
        mode=ModelAgentMode.SINGLE_AGENT,
    )
    session.id = uuid.uuid4()
    return session


def _setup_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_result: dict | None = None,
    stream_chunks: list[tuple[str, object]] | None = None,
) -> KbChatService:
    async def _dummy_get_state(_cls: object, _thread_id: str) -> _DummyCheckpoint:
        return _DummyCheckpoint()

    def _dummy_make_config(_cls: object, _thread_id: str) -> dict:
        return {}

    def _dummy_get_checkpointer(_cls: object) -> object | None:
        return None

    async def _dummy_build_tool_registry(
        *_args: object, **_kwargs: object
    ) -> tuple[list, dict]:
        return [], {}

    def _dummy_build_kb_retrieve_tool(*_args: object, **_kwargs: object) -> object:
        return object()

    def _dummy_build_chat_model_profile(*_args: object, **_kwargs: object) -> dict:
        return {}

    def _dummy_get_store(_cls: object) -> object | None:
        return None

    monkeypatch.setattr(kb_chat_service, "ChatOpenAI", _DummyChatOpenAI)
    monkeypatch.setattr(
        kb_chat_service, "build_tool_registry", _dummy_build_tool_registry
    )
    monkeypatch.setattr(
        kb_chat_service, "build_kb_retrieve_tool", _dummy_build_kb_retrieve_tool
    )
    monkeypatch.setattr(
        kb_chat_service, "build_chat_model_profile", _dummy_build_chat_model_profile
    )
    monkeypatch.setattr(
        kb_chat_service.CheckpointManager, "get_state", classmethod(_dummy_get_state)
    )
    monkeypatch.setattr(
        kb_chat_service.CheckpointManager,
        "make_config",
        classmethod(_dummy_make_config),
    )
    monkeypatch.setattr(
        kb_chat_service.CheckpointManager,
        "get_checkpointer",
        classmethod(_dummy_get_checkpointer),
    )
    monkeypatch.setattr(
        kb_chat_service.StoreManager, "get_store", classmethod(_dummy_get_store)
    )

    service = KbChatService.__new__(KbChatService)
    service._db = _DummyDb()
    service._llm = SimpleNamespace()
    service._settings = SimpleNamespace(
        app_env="dev",
        context_history_max_messages=3,
        kb_chat_force_retrieve=False,
        kb_chat_trace_enabled=False,
        kb_chat_total_timeout_seconds=45.0,
        kb_chat_json_safe_policy="fail_fast",
        kb_chat_grader_fail_policy="open",
        llm_model="dummy",
        llm_api_key="test",
        llm_base_url="http://localhost",
        memory_enabled=False,
    )
    service._retrieval = _DummyRetrieval()
    service._context_builder = _DummyContextBuilder()
    service._summary_service = _DummySummaryService()
    service._prompts = _DummyPrompts()

    run_result = run_result or {"messages": [], "pending_tool_calls": []}
    service._build_graph = lambda **_kwargs: _DummyGraph(
        run_result=run_result,
        stream_chunks=stream_chunks or [],
    )

    async def _dummy_finalize_run(**kwargs: object) -> ChatAnswerResponse:
        run = kwargs.get("run")
        status = kwargs.get("status", AgentRunStatus.SUCCEEDED)
        if run is not None:
            run.status = status
            run.stage_summaries = kwargs.get("stage_summaries")
            run.error_message = kwargs.get("error_message")
        return _build_answer_response()

    service._finalize_run = _dummy_finalize_run
    return service


@pytest.mark.asyncio
async def test_kb_chat_json_never_pending_tool_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _build_session()

    service = _setup_service(
        monkeypatch,
        run_result={"messages": [], "pending_tool_calls": [{"tool": "x"}]},
    )
    with pytest.raises(AppError, match="KB_CHAT_TOOL_APPROVAL_UNSUPPORTED"):
        await service.answer(session=session, user_content="hi")

    service = _setup_service(monkeypatch)
    response = await service.answer(session=session, user_content="hi")
    assert response.status == "succeeded"


@pytest.mark.asyncio
async def test_kb_chat_sse_meta_contains_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _build_session()
    token = SimpleNamespace(content="hello")
    stream_chunks = [("messages", (token, {}))]
    service = _setup_service(monkeypatch, stream_chunks=stream_chunks)

    events = []
    async for event, data in service.answer_stream(session=session, user_content="hi"):
        events.append((event, data))
        if event == "final":
            break

    meta = next(item for item in events if item[0] == "meta")[1]
    assert isinstance(meta.get("run_id"), str)
    assert "runId" not in meta


@pytest.mark.asyncio
async def test_kb_chat_sse_final_is_chat_answer_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _build_session()
    token = SimpleNamespace(content="hello")
    stream_chunks = [("messages", (token, {}))]
    service = _setup_service(monkeypatch, stream_chunks=stream_chunks)

    final_payload = None
    async for event, data in service.answer_stream(session=session, user_content="hi"):
        if event == "final":
            final_payload = data
            break

    assert final_payload is not None
    parsed = ChatAnswerResponse.model_validate(final_payload)
    assert parsed.status == "succeeded"


class _SlowGraph:
    def __init__(self, delay: float) -> None:
        self._delay = delay
        self.canceled = False

    async def run(self, *_args: object, **_kwargs: object) -> dict:
        await asyncio.sleep(self._delay)
        return {"messages": [], "pending_tool_calls": []}

    def compile(self, *_args: object, **_kwargs: object) -> "_SlowGraph":
        return self

    async def astream(self, *_args: object, **_kwargs: object):
        try:
            await asyncio.sleep(self._delay)
            if False:
                yield ("messages", (SimpleNamespace(content=""), {}))
        except asyncio.CancelledError:
            self.canceled = True
            raise


@pytest.mark.asyncio
async def test_kb_chat_answer_timeout_marks_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _build_session()
    service = _setup_service(monkeypatch)
    service._settings.kb_chat_total_timeout_seconds = 0.01
    service._build_graph = lambda **_kwargs: _SlowGraph(delay=0.05)

    await service.answer(session=session, user_content="hi")

    run = next(obj for obj in service._db._added if isinstance(obj, AgentRun))
    assert run.status == AgentRunStatus.FAILED
    assert run.stage_summaries["service_guardrail"]["reason"] == "timeout"


class _DisconnectRequest:
    async def is_disconnected(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_kb_chat_stream_disconnect_marks_canceled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _build_session()
    graph = _SlowGraph(delay=0.05)
    service = _setup_service(monkeypatch)
    service._build_graph = lambda **_kwargs: graph

    events = []
    async for event, data in service.answer_stream(
        session=session, user_content="hi", request=_DisconnectRequest()
    ):
        events.append((event, data))

    run = next(obj for obj in service._db._added if isinstance(obj, AgentRun))
    assert run.status == AgentRunStatus.CANCELED
    assert graph.canceled is True


@pytest.mark.asyncio
async def test_kb_chat_stream_timeout_marks_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _build_session()
    service = _setup_service(monkeypatch)
    service._settings.kb_chat_total_timeout_seconds = 0.01
    graph = _SlowGraph(delay=0.05)
    service._build_graph = lambda **_kwargs: graph

    final_payload = None
    async for event, data in service.answer_stream(session=session, user_content="hi"):
        if event == "final":
            final_payload = data
            break

    assert final_payload is not None
    run = next(obj for obj in service._db._added if isinstance(obj, AgentRun))
    assert run.status == AgentRunStatus.FAILED
    assert run.stage_summaries["service_guardrail"]["reason"] == "timeout"
    assert graph.canceled is True

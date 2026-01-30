import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage

import app.services.kb_chat_service as kb_chat_service
from app.models.chat_session import AgentMode as ModelAgentMode
from app.models.chat_session import ChatSession, ChatSessionType
from app.schemas.chats import (
    AgentMode,
    AgentRunRead,
    AgentRunStatus,
    AgentRunType,
    ChatAnswerResponse,
    ChatMessageRead,
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
    def build_history_messages(self, *, history: list[object], summary_text: str | None):
        return [], {"tokens": 0, "chars": 0, "messages": 0}, {"truncated": False}

    def build_metrics(self, **_kwargs: object) -> dict:
        return {}


class _DummySummaryService:
    async def load_latest_summary(self, _session_id: uuid.UUID) -> object | None:
        return None

    def is_summary_message(self, _msg: object) -> bool:
        return False


class _DummyPrompts:
    def render(self, _name: str) -> str:
        return "system"


class _DummyCheckpoint:
    def __init__(self) -> None:
        # Make KB chat use checkpoint messages so it doesn't hit DB history in tests.
        self.checkpoint = {"channel_values": {"messages": ["stub"]}}
        self.pending_writes = None


class _DummyChatOpenAI:
    def __init__(self, *args: object, **_kwargs: object) -> None:
        self.args = args


class _CaptureKbTool:
    name = "kb_retrieve"

    def __init__(self, on_results) -> None:
        self._on_results = on_results
        self._call_count = 0

    async def ainvoke(self, _payload: dict) -> str:
        self._call_count += 1

        kb_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        material_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        chunk1 = uuid.UUID("00000000-0000-0000-0000-000000000011")
        chunk2 = uuid.UUID("00000000-0000-0000-0000-000000000022")

        if self._call_count == 1:
            evidence_items = [
                {
                    "source_kind": "kb",
                    "kb_id": str(kb_id),
                    "material_id": str(material_id),
                    "chunk_id": str(chunk1),
                    "locator": {},
                    "excerpt": "first",
                    "score": 1.0,
                    "hits": [],
                }
            ]
            self._on_results([], {"evidence_items": evidence_items, "usage": {}, "truncation": {}, "kb_scope": {}})
            return "[1] first"

        evidence_items = [
            {
                "source_kind": "kb",
                "kb_id": str(kb_id),
                "material_id": str(material_id),
                "chunk_id": str(chunk2),
                "locator": {},
                "excerpt": "second",
                "score": 1.0,
                "hits": [],
            }
        ]
        self._on_results([], {"evidence_items": evidence_items, "usage": {}, "truncation": {}, "kb_scope": {}})
        return "[1] second"


class _DummyGraph:
    def __init__(self, tool: _CaptureKbTool) -> None:
        self._tool = tool

    async def run(self, *_args: object, **_kwargs: object) -> dict:
        # Simulate an agent that retries retrieval and only the LAST retrieval context should
        # determine the final evidence list order.
        await self._tool.ainvoke({"query": "q"})
        await self._tool.ainvoke({"query": "q2"})
        return {"messages": [AIMessage(content="answer [1]")], "pending_tool_calls": []}


def _build_session() -> ChatSession:
    session = ChatSession(
        session_type=ChatSessionType.KB_CHAT,
        selected_kb_ids=[uuid.UUID("00000000-0000-0000-0000-000000000001")],
        allow_external=False,
        mode=ModelAgentMode.SINGLE_AGENT,
    )
    session.id = uuid.uuid4()
    return session


def _build_answer_response(*, run_id: uuid.UUID) -> ChatAnswerResponse:
    now = datetime.now(timezone.utc)
    assistant = ChatMessageRead(
        id=uuid.uuid4(),
        role=MessageRole.ASSISTANT,
        content="ok",
        created_at=now,
    )
    run = AgentRunRead(
        id=run_id,
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
    return ChatAnswerResponse(
        assistant_message=assistant,
        evidence=[],
        run=run,
    )


@pytest.mark.asyncio
async def test_kb_chat_evidence_list_tracks_latest_retrieval_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _dummy_get_state(_cls: object, _thread_id: str) -> _DummyCheckpoint:
        return _DummyCheckpoint()

    def _dummy_get_checkpointer(_cls: object) -> object | None:
        return None

    async def _dummy_build_tool_registry(*_args: object, **kwargs: object):
        # Return the kb_retrieve tool built by build_kb_retrieve_tool patch below.
        tools = kwargs.get("extra_tools") or []
        return list(tools), {}

    def _dummy_build_chat_model_profile(*_args: object, **_kwargs: object) -> dict:
        return {}

    def _dummy_get_store(_cls: object) -> object | None:
        return None

    monkeypatch.setattr(kb_chat_service, "ChatOpenAI", _DummyChatOpenAI)
    monkeypatch.setattr(
        kb_chat_service.CheckpointManager, "get_state", classmethod(_dummy_get_state)
    )
    monkeypatch.setattr(
        kb_chat_service.CheckpointManager,
        "get_checkpointer",
        classmethod(_dummy_get_checkpointer),
    )
    monkeypatch.setattr(
        kb_chat_service, "build_tool_registry", _dummy_build_tool_registry
    )
    monkeypatch.setattr(
        kb_chat_service, "build_chat_model_profile", _dummy_build_chat_model_profile
    )
    monkeypatch.setattr(
        kb_chat_service.StoreManager, "get_store", classmethod(_dummy_get_store)
    )

    captured: dict[str, object] = {}

    def _dummy_build_kb_retrieve_tool(*_args: object, **kwargs: object):
        return _CaptureKbTool(kwargs.get("on_results"))

    monkeypatch.setattr(
        kb_chat_service, "build_kb_retrieve_tool", _dummy_build_kb_retrieve_tool
    )

    service = KbChatService.__new__(KbChatService)
    service._db = _DummyDb()
    service._llm = SimpleNamespace()
    service._settings = SimpleNamespace(
        app_env="dev",
        context_history_max_messages=3,
        kb_chat_force_retrieve=False,
        kb_chat_trace_enabled=False,
        kb_chat_total_timeout_seconds=5.0,
        kb_chat_json_safe_policy="fail_fast",
        kb_chat_grader_fail_policy="open",
        llm_model="dummy",
        llm_api_key="test",
        llm_base_url="http://localhost",
        memory_enabled=False,
    )
    service._retrieval = SimpleNamespace(last_stats=None, last_layer_draft=None)
    service._context_builder = _DummyContextBuilder()
    service._summary_service = _DummySummaryService()
    service._prompts = _DummyPrompts()

    # Force a graph that triggers multiple retrieval calls.
    def _build_graph(*, tools: list, **_kwargs: object):
        tool = next(t for t in tools if getattr(t, "name", None) == "kb_retrieve")
        return _DummyGraph(tool=tool)  # type: ignore[arg-type]

    service._build_graph = _build_graph  # type: ignore[assignment]

    async def _dummy_finalize_run(**kwargs: object) -> ChatAnswerResponse:
        evidence_draft_items = kwargs.get("evidence_draft_items")
        captured["evidence_draft_items"] = evidence_draft_items
        run = kwargs.get("run")
        run_id = getattr(run, "id", None) or uuid.uuid4()
        return _build_answer_response(run_id=run_id)

    service._finalize_run = _dummy_finalize_run  # type: ignore[assignment]

    session = _build_session()
    await service.answer(session=session, user_content="hi")

    evidence_draft_items = captured.get("evidence_draft_items")
    assert isinstance(evidence_draft_items, list)
    assert len(evidence_draft_items) == 1

    only = evidence_draft_items[0]
    assert isinstance(only, dict)
    assert only.get("excerpt") == "second"

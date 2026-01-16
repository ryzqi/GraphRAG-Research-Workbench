from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

import app.services.kb_chat_service as kb_chat_service_mod
from app.models.chat_session import AgentMode, ChatSession, ChatSessionType
from app.models.document_chunk import DocumentChunk
from app.models.evidence import Evidence
from app.services.context_builder import ContextBuilder
from app.services.retrieval_service import RetrievalResult


class FakeAsyncSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def add_all(self, objs: list[object]) -> None:
        self.added.extend(objs)

    async def flush(self) -> None:
        self._assign_ids()

    async def commit(self) -> None:
        self._assign_ids()

    async def refresh(self, _obj: object) -> None:
        return None

    def _assign_ids(self) -> None:
        now = datetime.now(timezone.utc)
        for obj in self.added:
            if hasattr(obj, "id") and getattr(obj, "id") is None:
                setattr(obj, "id", uuid.uuid4())
            if hasattr(obj, "created_at") and getattr(obj, "created_at") is None:
                setattr(obj, "created_at", now)
            if hasattr(obj, "updated_at") and getattr(obj, "updated_at") is None:
                setattr(obj, "updated_at", now)


class DummySummaryService:
    async def load_latest_summary(self, _session_id):
        return None

    async def maybe_update_summary(self, _session_id):
        return None


class FakeRetrievalService:
    def __init__(self, results: list[RetrievalResult]) -> None:
        self._results = results
        self._last_stats = None

    @property
    def last_stats(self):
        return self._last_stats

    async def retrieve(self, *, query: str, kb_ids: list[uuid.UUID], top_k=None):
        return self._results


class FakeBoundModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)

    async def ainvoke(self, _messages):
        return self._responses.pop(0)


class FakeChatOpenAI:
    def __init__(self, *_, **__) -> None:
        # 第一次：强制调用 kb_retrieve；第二次：生成最终回答。
        self._forced = FakeBoundModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "kb_retrieve",
                            "args": {"query": "问题"},
                            "id": "call_1",
                        }
                    ],
                )
            ]
        )
        self._auto = FakeBoundModel([AIMessage(content="最终答案 [1]")])
        self._no_tools = FakeBoundModel([AIMessage(content="unused")])

    def bind_tools(self, _tools, tool_choice=None):
        if tool_choice == "none":
            return self._no_tools
        if isinstance(tool_choice, dict):
            return self._forced
        return self._auto


@pytest.mark.asyncio
async def test_kb_chat_service_persists_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()

    chunks = [
        DocumentChunk(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            chunk_index=0,
            text="第一段",
            locator={"page": 1},
        ),
        DocumentChunk(
            id=uuid.uuid4(),
            kb_id=kb_id,
            material_id=material_id,
            chunk_index=1,
            text="第二段",
            locator={"page": 2},
        ),
    ]
    retrieval_results = [
        RetrievalResult(chunk=chunks[0], score=0.1),
        RetrievalResult(chunk=chunks[1], score=0.2),
    ]

    # Patch：避免真实 LLM/Checkpointer 依赖
    monkeypatch.setattr(kb_chat_service_mod, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(
        kb_chat_service_mod.CheckpointManager,
        "get_checkpointer",
        lambda: MemorySaver(),
    )

    db = FakeAsyncSession()

    service = kb_chat_service_mod.KbChatService.__new__(kb_chat_service_mod.KbChatService)
    service._db = db
    service._llm = object()
    service._settings = kb_chat_service_mod.get_settings()
    service._retrieval = FakeRetrievalService(retrieval_results)
    service._context_builder = ContextBuilder(service._settings)
    service._summary_service = DummySummaryService()
    service._prompts = kb_chat_service_mod.get_prompt_loader()

    async def _load_history(_session_id, limit: int):
        return []

    service._load_history = _load_history

    session = ChatSession(
        id=uuid.uuid4(),
        session_type=ChatSessionType.KB_CHAT,
        selected_kb_ids=[kb_id],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
    )

    resp = await service.answer(session=session, user_content="问题")

    assert len(resp.evidence) == 2
    persisted = [obj for obj in db.added if isinstance(obj, Evidence)]
    assert len(persisted) == 2

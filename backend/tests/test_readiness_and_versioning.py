from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.models.knowledge_base import KnowledgeBaseReadiness, KnowledgeBaseStatus
from app.schemas.chats import AgentMode, ChatSessionCreate, ChatSessionType
from app.schemas.research import ResearchRunCreateRequest
from app.services.index_rebuild_service import IndexRebuildService
from app.services.research_service import ResearchService


@pytest.mark.asyncio
async def test_chat_session_creation_rejects_non_selectable_kb(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1.endpoints import chats as chats_ep

    kb_id = uuid.uuid4()

    class _KbService:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_ids(self, _kb_ids: list[uuid.UUID]) -> list[object]:
            return [
                SimpleNamespace(
                    id=kb_id,
                    status=KnowledgeBaseStatus.ACTIVE,
                    readiness=KnowledgeBaseReadiness.NOT_READY,
                )
            ]

    monkeypatch.setattr(chats_ep, "KnowledgeBaseService", _KbService)

    body = ChatSessionCreate(
        session_type=ChatSessionType.KB_CHAT,
        selected_kb_ids=[kb_id],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
    )

    with pytest.raises(AppError) as exc:
        await chats_ep.create_chat_session(db=object(), body=body)

    assert exc.value.code == "KB_NOT_SELECTABLE"


class _ScalarResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> list[object]:
        return self._values


class _ResearchSession:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    async def execute(self, _stmt: object) -> _ScalarResult:
        return _ScalarResult(self._values)


@pytest.mark.asyncio
async def test_research_run_creation_rejects_non_selectable_kb() -> None:
    kb_id = uuid.uuid4()
    session = _ResearchSession(
        [
            SimpleNamespace(
                id=kb_id,
                status=KnowledgeBaseStatus.ACTIVE,
                readiness=KnowledgeBaseReadiness.NOT_READY,
            )
        ]
    )

    service = ResearchService(celery=SimpleNamespace(send_task=lambda *args, **kwargs: None))
    req = ResearchRunCreateRequest(
        question="q",
        selected_kb_ids=[kb_id],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
    )

    with pytest.raises(AppError) as exc:
        await service.create_run(session, req)

    assert exc.value.code == "KB_NOT_SELECTABLE"


class _IndexRebuildExecuteResult:
    def scalars(self) -> "_IndexRebuildExecuteResult":
        return self

    def all(self) -> list[object]:
        return []


class _IndexRebuildSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commit_called = False
        self.refreshed: list[object] = []

    async def execute(self, _stmt: object) -> _IndexRebuildExecuteResult:
        return _IndexRebuildExecuteResult()

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commit_called = True

    async def refresh(self, obj: object) -> None:
        self.refreshed.append(obj)


@pytest.mark.asyncio
async def test_index_rebuild_job_bumps_config_version_and_adds_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.worker.tasks import index_rebuild as index_rebuild_tasks

    delay_args: list[str] = []

    class _Task:
        @staticmethod
        def delay(job_id: str) -> None:
            delay_args.append(job_id)

    monkeypatch.setattr(index_rebuild_tasks, "run_index_rebuild_job", _Task)

    session = _IndexRebuildSession()
    kb = SimpleNamespace(
        id=uuid.uuid4(),
        current_config_version=1,
        index_config={"chunking": {"general_strategy": "sliding_window"}},
    )

    service = IndexRebuildService(session)  # type: ignore[arg-type]
    job = await service.create_job(kb=kb, index_config={"chunking": {"general_strategy": "parent_child"}})

    assert kb.current_config_version == 2
    assert kb.index_config == {"chunking": {"general_strategy": "parent_child"}}
    assert session.commit_called is True
    assert job in session.added
    assert len(delay_args) == 1

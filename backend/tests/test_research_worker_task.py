from __future__ import annotations

import uuid

import pytest

import app.worker.tasks.research as research_mod
from app.agents.research_graph import ResearchOutput
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_session import AgentMode
from app.models.evidence import Evidence
from app.models.research_report import ResearchReport
from app.services.retrieval_service import RetrievedChunk, RetrievalResult


class FakeSession:
    def __init__(self, run: AgentRun) -> None:
        self._run = run
        self.added: list[object] = []

    async def get(self, _model, _pk):
        return self._run

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def add_all(self, objs: list[object]) -> None:
        self.added.extend(objs)

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakeSessionMaker:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def __call__(self) -> FakeSessionContext:
        return FakeSessionContext(self._session)


class FakeRetrievalService:
    def __init__(self, _session, _milvus, _embedding, _redis):
        return None


class FakeCompiledGraph:
    async def astream(self, *_args, **_kwargs):
        if False:
            yield "updates", {}
        return


class FakeResearchGraph:
    async def build_runtime(self, **_kwargs):
        kb_id = uuid.uuid4()
        material_id = uuid.uuid4()
        chunks = [
            RetrievedChunk(
                id=uuid.uuid4(),
                kb_id=kb_id,
                material_id=material_id,
                content="证据1",
                context=None,
                locator={"page": 1},
                metadata=None,
                chunk_role="default",
                parent_chunk_id=None,
                child_seq=None,
            ),
            RetrievedChunk(
                id=uuid.uuid4(),
                kb_id=kb_id,
                material_id=material_id,
                content="证据2",
                context=None,
                locator={"page": 2},
                metadata=None,
                chunk_role="default",
                parent_chunk_id=None,
                child_seq=None,
            ),
        ]
        results = [
            RetrievalResult(chunk=chunks[0], score=0.1),
            RetrievalResult(chunk=chunks[1], score=0.2),
        ]
        state = {"messages": []}
        return FakeCompiledGraph(), state, None, results

    def build_output(self, _result_dict, retrieval_results):
        return ResearchOutput(
            report_md="报告内容",
            citations=[{"index": 1}, {"index": 2}],
            retrieval_results=retrieval_results,
            stage_summaries={"draft": {"ok": True}},
            metrics={"m": 1},
        )


@pytest.mark.asyncio
async def test_research_worker_writes_report_and_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = uuid.uuid4()
    run = AgentRun(
        id=run_id,
        run_type=AgentRunType.RESEARCH,
        session_id=None,
        question="q",
        selected_kb_ids=None,
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
        status=AgentRunStatus.RUNNING,
        started_at=None,
    )

    session = FakeSession(run)

    async def _noop() -> None:
        return None

    monkeypatch.setattr(research_mod.CheckpointManager, "initialize", _noop)
    monkeypatch.setattr(research_mod.CheckpointManager, "shutdown", _noop)
    monkeypatch.setattr(research_mod.CheckpointManager, "get_checkpointer", lambda: None)
    monkeypatch.setattr(research_mod, "get_sessionmaker", lambda: FakeSessionMaker(session))
    monkeypatch.setattr(research_mod, "get_milvus_client", lambda: object())
    monkeypatch.setattr(research_mod, "EmbeddingClient", lambda: object())
    monkeypatch.setattr(research_mod, "get_redis", lambda: object())
    monkeypatch.setattr(research_mod, "RetrievalService", FakeRetrievalService)
    monkeypatch.setattr(research_mod, "ResearchGraph", FakeResearchGraph)

    await research_mod._run_research(
        run_id=str(run_id),
        question="问题",
        kb_ids=[str(uuid.uuid4())],
        allow_external=False,
        mode="single_agent",
    )

    assert run.status == AgentRunStatus.SUCCEEDED, run.error_message
    assert run.final_output

    reports = [obj for obj in session.added if isinstance(obj, ResearchReport)]
    evidence = [obj for obj in session.added if isinstance(obj, Evidence)]

    assert len(reports) == 1
    assert len(evidence) == 2

from __future__ import annotations

import asyncio
import uuid

from app.models.research_artifact import ResearchArtifact
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.services.research_artifact_store import ResearchArtifactStore
from app.services.research_service import ResearchService


class _DummyDb:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


def _build_session() -> ResearchSession:
    session = ResearchSession(
        id=uuid.uuid4(),
        thread_id="thread-1",
        question="当前 RAG 领域的最新进展",
        status=ResearchSessionStatus.RUNNING,
    )
    session.artifacts = []
    session.events = []
    return session


def test_build_artifacts_response_normalizes_blank_optional_text_fields() -> None:
    session = _build_session()
    session.artifacts = [
        ResearchArtifact(
            artifact_key="runtime_report_draft_md",
            content_text="   ",
            source_provider="  ",
            retrieval_method="\n",
            origin_url="\t",
        )
    ]

    service = object.__new__(ResearchService)

    response = service.build_artifacts_response(session)

    assert response.status == ResearchSessionStatus.RUNNING
    artifact = next(
        item for item in response.items if item.artifact_key == "runtime_report_draft_md"
    )
    assert artifact.content_text is None
    assert artifact.source_provider is None
    assert artifact.retrieval_method is None
    assert artifact.origin_url is None


def test_artifact_store_upsert_normalizes_blank_optional_text_fields() -> None:
    session = _build_session()
    store = ResearchArtifactStore(_DummyDb())  # type: ignore[arg-type]

    artifact = asyncio.run(
        store.upsert(
            session=session,
            artifact_key="runtime_report_draft_md",
            content_text="   ",
            source_provider="  ",
            retrieval_method="\n",
            origin_url="\t",
        )
    )

    assert artifact.content_text is None
    assert artifact.source_provider is None
    assert artifact.retrieval_method is None
    assert artifact.origin_url is None

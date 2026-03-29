from __future__ import annotations

import uuid

import pytest

from app.models.research_artifact import ResearchArtifact
from app.services.research_artifact_store import ResearchArtifactStore


class _FakeResult:
    def __init__(self, artifact: ResearchArtifact | None) -> None:
        self._artifact = artifact

    def scalar_one_or_none(self) -> ResearchArtifact | None:
        return self._artifact


class _FakeAsyncSession:
    def __init__(self, artifact: ResearchArtifact | None = None) -> None:
        self.artifact = artifact
        self.executed = 0
        self.added: list[ResearchArtifact] = []

    async def execute(self, stmt):  # noqa: ANN001
        del stmt
        self.executed += 1
        return _FakeResult(self.artifact)

    def add(self, artifact: ResearchArtifact) -> None:
        self.added.append(artifact)


class _RelationshipAccessGuard:
    def __init__(self) -> None:
        self.id = uuid.uuid4()

    @property
    def artifacts(self) -> list[ResearchArtifact]:
        raise AssertionError("未预加载 relationship 时不应直接访问 session.artifacts")


class _LoadedArtifactsSession:
    def __init__(self, artifact: ResearchArtifact) -> None:
        self.id = artifact.session_id
        self.artifacts = [artifact]


@pytest.mark.asyncio
async def test_artifact_store_queries_db_when_session_artifacts_not_preloaded() -> None:
    db = _FakeAsyncSession()
    store = ResearchArtifactStore(db)
    session = _RelationshipAccessGuard()

    artifact = await store.upsert(
        session=session,
        artifact_key="plan_snapshot",
        content_json={"ok": True},
    )

    assert db.executed == 1
    assert len(db.added) == 1
    assert artifact is db.added[0]
    assert artifact.session_id == session.id
    assert artifact.artifact_key == "plan_snapshot"
    assert artifact.content_json == {"ok": True}


@pytest.mark.asyncio
async def test_artifact_store_reuses_loaded_relationship_when_available() -> None:
    existing = ResearchArtifact(
        session_id=uuid.uuid4(),
        artifact_key="plan_snapshot",
        content_json={"old": True},
    )
    session = _LoadedArtifactsSession(existing)
    db = _FakeAsyncSession()
    store = ResearchArtifactStore(db)

    artifact = await store.upsert(
        session=session,
        artifact_key="plan_snapshot",
        content_json={"new": True},
    )

    assert db.executed == 0
    assert db.added == []
    assert artifact is existing
    assert artifact.content_json == {"new": True}

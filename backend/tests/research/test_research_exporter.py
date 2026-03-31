from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.models.export_job import ExportStatus
from app.models.research_artifact import ResearchArtifact
from app.schemas.exports import ExportCreateRequest
from app.services.export_service import ExportService
from app.services.exporters.research_exporter import ResearchExporter
from app.worker.tasks import export as export_task_module


class _ScalarResult:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> list[object]:
        return list(self._items)


class _FakeAsyncSession:
    def __init__(self, *, artifacts: list[ResearchArtifact] | None = None) -> None:
        self.artifacts = list(artifacts or [])
        self.added: list[object] = []
        self.commit_calls = 0
        self.refresh_calls = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(self, obj: object) -> None:
        self.refresh_calls += 1

    async def execute(self, stmt) -> _ScalarResult:  # type: ignore[no-untyped-def]
        del stmt
        return _ScalarResult(self.artifacts)

    async def get(self, model, key):  # type: ignore[no-untyped-def]
        del model, key
        return None


class _FakeCelery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def send_task(self, name: str, args: list[str]) -> None:
        self.calls.append((name, list(args)))


def _artifact(
    *,
    session_id: uuid.UUID,
    artifact_key: str,
    content_text: str | None = None,
    content_json: dict | list | None = None,
) -> ResearchArtifact:
    return ResearchArtifact(
        session_id=session_id,
        artifact_key=artifact_key,
        content_text=content_text,
        content_json=content_json,
    )


async def test_research_exporter_reads_report_artifacts_by_session_id() -> None:
    session_id = uuid.uuid4()
    exporter = ResearchExporter()
    session = _FakeAsyncSession(
        artifacts=[
            _artifact(
                session_id=session_id,
                artifact_key="report_json",
                content_json={
                    "question": "什么是 deep research?",
                    "claim_map": [{"claim": "deep research 需要证据", "verdict": "supported"}],
                    "coverage_matrix": {"provider_counts": {"tavily": 1}},
                    "conflicts": [],
                    "source_ledger": [
                        {
                            "provider": "tavily",
                            "origin_url": "https://example.com/a",
                            "title": "A",
                            "source_type": "web",
                        }
                    ],
                },
            ),
            _artifact(
                session_id=session_id,
                artifact_key="report_md",
                content_text="# 报告\n\n这里是最终 Markdown。",
            ),
        ]
    )

    content = await exporter.export(session, session_id)

    assert content == "# 报告\n\n这里是最终 Markdown。"


async def test_research_exporter_raises_artifact_incomplete_when_required_artifacts_missing() -> None:
    session_id = uuid.uuid4()
    exporter = ResearchExporter()
    session = _FakeAsyncSession(
        artifacts=[
            _artifact(
                session_id=session_id,
                artifact_key="report_json",
                content_json={"question": "只剩 JSON，没有 Markdown"},
            )
        ]
    )

    with pytest.raises(AppError) as exc_info:
        await exporter.export(session, session_id)

    assert exc_info.value.code == "ARTIFACT_INCOMPLETE"
    assert exc_info.value.details == {
        "session_id": str(session_id),
        "missing_artifact_keys": ["report_md"],
        "available_artifact_keys": ["report_json"],
    }


async def test_export_service_queues_research_export_using_session_id() -> None:
    session_id = uuid.uuid4()
    fake_celery = _FakeCelery()
    fake_db = _FakeAsyncSession()
    service = ExportService(celery=fake_celery)

    job = await service.create_export(
        fake_db,
        ExportCreateRequest(type="research", session_id=session_id),
    )

    assert job.status == ExportStatus.QUEUED
    assert job.session_id == session_id
    assert job.run_id is None
    assert fake_db.commit_calls == 1
    assert fake_db.refresh_calls == 1
    assert fake_celery.calls == [
        (
            "app.worker.tasks.export.run_export",
            [str(job.id), "research", str(session_id)],
        )
    ]


async def test_run_export_persists_structured_artifact_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    export_id = uuid.uuid4()
    session_id = uuid.uuid4()
    job = SimpleNamespace(
        status=ExportStatus.QUEUED,
        error_code=None,
        error_message=None,
        download_url=None,
    )

    class _WorkerSession(_FakeAsyncSession):
        async def get(self, model, key):  # type: ignore[no-untyped-def]
            del model, key
            return job

    worker_session = _WorkerSession()

    class _SessionContext:
        async def __aenter__(self):
            return worker_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Sessionmaker:
        def __call__(self):
            return _SessionContext()

    @asynccontextmanager
    async def _fake_managed_task_resources(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        yield SimpleNamespace(sessionmaker=_Sessionmaker())

    class _FakeStorage:
        async def ensure_buckets(self) -> None:
            return None

    async def _raise_artifact_incomplete(self, session, target_session_id):  # type: ignore[no-untyped-def]
        del self, session
        raise AppError(
            code="ARTIFACT_INCOMPLETE",
            message="研究工件不完整，暂时无法导出",
            status_code=409,
            details={"session_id": str(target_session_id)},
        )

    monkeypatch.setattr(
        export_task_module,
        "managed_task_resources",
        _fake_managed_task_resources,
    )
    monkeypatch.setattr(export_task_module, "ObjectStorage", _FakeStorage)
    monkeypatch.setattr(ResearchExporter, "export", _raise_artifact_incomplete)

    await export_task_module._run_export(
        export_id=str(export_id),
        export_type="research",
        target_id=str(session_id),
    )

    assert job.status == ExportStatus.FAILED
    assert job.error_code == "ARTIFACT_INCOMPLETE"
    assert "session_id" in str(job.error_message)

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.api.v1.endpoints import exports as exports_endpoint
from app.api.v1.endpoints import materials as materials_endpoint
from app.core.errors import AppError
from app.core.settings import Settings
from app.models.export_job import ExportStatus
from app.models.source_material import SourceType
from app.schemas.exports import ExportCreateRequest, ExportType
from app.worker.tasks import export as export_task


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, minio_bucket_exports="exports", **overrides)


def _make_async_iter(chunks: list[bytes]):
    async def _generator():
        for chunk in chunks:
            yield chunk

    return _generator()


class _FakeExportSession:
    def __init__(self, job: SimpleNamespace | None) -> None:
        self._job = job
        self.commit_calls = 0

    async def get(self, model, identity):  # noqa: ANN001, ANN201
        assert model is export_task.ExportJob
        assert identity == self._job.id
        return self._job

    async def commit(self) -> None:
        self.commit_calls += 1


class _FakeExportSessionScope:
    def __init__(self, session: _FakeExportSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeExportSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeExportSessionmaker:
    def __init__(self, session: _FakeExportSession) -> None:
        self._session = session

    def __call__(self) -> _FakeExportSessionScope:
        return _FakeExportSessionScope(self._session)


@pytest.mark.asyncio
async def test_run_export_sets_relative_download_url(monkeypatch: pytest.MonkeyPatch) -> None:
    export_id = uuid.uuid4()
    target_id = uuid.uuid4()
    settings = _make_settings()
    job = SimpleNamespace(
        id=export_id,
        status=ExportStatus.QUEUED,
        error_message=None,
        error_code=None,
        download_url=None,
        run_id=target_id,
        session_id=None,
    )
    session = _FakeExportSession(job)
    sessionmaker = _FakeExportSessionmaker(session)
    put_text_calls: list[tuple[str, str, str]] = []

    class _FakeStorage:
        async def ensure_buckets(self) -> None:
            return None

        async def put_text(self, ref, content: str, *, content_type: str) -> None:  # noqa: ANN001
            put_text_calls.append((ref.bucket, ref.object_name, content_type))

        async def put_bytes(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            raise AssertionError("chat export should use put_text")

        async def presign_get(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
            raise AssertionError("M23 should no longer use presign_get for export download_url")

    class _FakeChatExporter:
        async def export(self, db, requested_id: uuid.UUID) -> str:  # noqa: ANN001
            assert db is session
            assert requested_id == target_id
            return "# export"

    @asynccontextmanager
    async def _fake_managed_task_resources(**_kwargs):
        yield SimpleNamespace(
            sessionmaker=sessionmaker,
            object_storage=_FakeStorage(),
        )

    monkeypatch.setattr(export_task, "get_settings", lambda: settings)
    monkeypatch.setattr(export_task, "managed_task_resources", _fake_managed_task_resources)
    monkeypatch.setattr(export_task, "ChatExporter", _FakeChatExporter)

    await export_task._run_export(
        export_id=str(export_id),
        export_type="chat",
        target_id=str(target_id),
    )

    assert put_text_calls == [
        (
            settings.minio_bucket_exports,
            f"exports/chat/{export_id}.md",
            "text/markdown; charset=utf-8",
        )
    ]
    assert job.status is ExportStatus.SUCCEEDED
    assert job.download_url == f"/api/v1/exports/{export_id}/download"
    assert session.commit_calls == 2


@pytest.mark.asyncio
async def test_download_export_streams_research_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download_export = getattr(exports_endpoint, "download_export", None)
    assert download_export is not None, "missing exports.download_export endpoint"

    export_id = uuid.uuid4()
    session_id = uuid.uuid4()
    settings = _make_settings()
    iter_calls: list[tuple[str, str, int]] = []
    exists_calls: list[tuple[str, str]] = []

    async def _iter_bytes(ref, *, chunk_size: int = 1024 * 1024):  # noqa: ANN001
        iter_calls.append((ref.bucket, ref.object_name, chunk_size))
        async for chunk in _make_async_iter([b"pdf-", b"data"]):
            yield chunk

    async def _exists(ref) -> bool:  # noqa: ANN001
        exists_calls.append((ref.bucket, ref.object_name))
        return True

    class _FakeService:
        async def get_export(self, db, requested_id: uuid.UUID):  # noqa: ANN001, ANN201
            assert requested_id == export_id
            return SimpleNamespace(
                id=export_id,
                status=ExportStatus.SUCCEEDED,
                run_id=None,
                session_id=session_id,
            )

    storage = SimpleNamespace(
        ensure_buckets=lambda: None,
        exists=_exists,
        iter_bytes=_iter_bytes,
    )

    async def _ensure_buckets() -> None:
        return None

    storage.ensure_buckets = _ensure_buckets
    monkeypatch.setattr(exports_endpoint, "get_settings", lambda: settings)

    response = await download_export(
        export_id=export_id,
        session=object(),
        service=_FakeService(),
        resources=SimpleNamespace(object_storage=storage),
    )

    assert isinstance(response, StreamingResponse)
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert body == b"pdf-data"
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="research-report-{session_id}.pdf"'
    )
    assert exists_calls == [
        (
            settings.minio_bucket_exports,
            f"exports/research/{export_id}.pdf",
        )
    ]
    assert iter_calls == [
        (
            settings.minio_bucket_exports,
            f"exports/research/{export_id}.pdf",
            1024 * 1024,
        )
    ]


@pytest.mark.asyncio
async def test_download_export_streams_chat_file_with_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download_export = getattr(exports_endpoint, "download_export", None)
    assert download_export is not None, "missing exports.download_export endpoint"

    export_id = uuid.uuid4()
    run_id = uuid.uuid4()
    settings = _make_settings()
    exists_calls: list[tuple[str, str]] = []

    async def _exists(ref) -> bool:  # noqa: ANN001
        exists_calls.append((ref.bucket, ref.object_name))
        return True

    async def _iter_bytes(ref, *, chunk_size: int = 1024 * 1024):  # noqa: ANN001
        async for chunk in _make_async_iter([b"# ", b"chat"]):
            yield chunk

    async def _ensure_buckets() -> None:
        return None

    class _FakeService:
        async def get_export(self, db, requested_id: uuid.UUID):  # noqa: ANN001, ANN201
            assert requested_id == export_id
            return SimpleNamespace(
                id=export_id,
                status=ExportStatus.SUCCEEDED,
                run_id=run_id,
                session_id=None,
            )

    monkeypatch.setattr(exports_endpoint, "get_settings", lambda: settings)

    response = await download_export(
        export_id=export_id,
        session=object(),
        service=_FakeService(),
        resources=SimpleNamespace(
            object_storage=SimpleNamespace(
                ensure_buckets=_ensure_buckets,
                exists=_exists,
                iter_bytes=_iter_bytes,
            )
        ),
    )

    assert isinstance(response, StreamingResponse)
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert body == b"# chat"
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{export_id}.md"'
    )
    assert exists_calls == [
        (
            settings.minio_bucket_exports,
            f"exports/chat/{export_id}.md",
        )
    ]


@pytest.mark.asyncio
async def test_download_export_rejects_ambiguous_target_fields() -> None:
    download_export = getattr(exports_endpoint, "download_export", None)
    assert download_export is not None, "missing exports.download_export endpoint"

    export_id = uuid.uuid4()

    class _FakeService:
        async def get_export(self, db, requested_id: uuid.UUID):  # noqa: ANN001, ANN201
            assert requested_id == export_id
            return SimpleNamespace(
                id=export_id,
                status=ExportStatus.SUCCEEDED,
                run_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
            )

    with pytest.raises(AppError) as exc_info:
        await download_export(
            export_id=export_id,
            session=object(),
            service=_FakeService(),
            resources=SimpleNamespace(object_storage=SimpleNamespace()),
        )

    assert exc_info.value.code == "EXPORT_TARGET_AMBIGUOUS"
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_download_export_rejects_failed_job() -> None:
    download_export = getattr(exports_endpoint, "download_export", None)
    assert download_export is not None, "missing exports.download_export endpoint"

    export_id = uuid.uuid4()

    class _FakeService:
        async def get_export(self, db, requested_id: uuid.UUID):  # noqa: ANN001, ANN201
            assert requested_id == export_id
            return SimpleNamespace(
                id=export_id,
                status=ExportStatus.FAILED,
                run_id=uuid.uuid4(),
                session_id=None,
                error_code="EXPORT_FAILED",
                error_message="导出失败",
            )

    with pytest.raises(AppError) as exc_info:
        await download_export(
            export_id=export_id,
            session=object(),
            service=_FakeService(),
            resources=SimpleNamespace(object_storage=SimpleNamespace()),
        )

    assert exc_info.value.code == "EXPORT_FAILED"
    assert exc_info.value.message == "导出失败"
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_download_material_streams_uploaded_object() -> None:
    download_material = getattr(materials_endpoint, "download_material", None)
    assert download_material is not None, "missing materials.download_material endpoint"

    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    object_name = f"{kb_id}/{material_id}/report.pdf"
    iter_calls: list[tuple[str, str]] = []
    exists_calls: list[tuple[str, str]] = []

    async def _iter_bytes(ref, *, chunk_size: int = 1024 * 1024):  # noqa: ANN001
        iter_calls.append((ref.bucket, ref.object_name))
        async for chunk in _make_async_iter([b"a", b"b"]):
            yield chunk

    async def _exists(ref) -> bool:  # noqa: ANN001
        exists_calls.append((ref.bucket, ref.object_name))
        return True

    async def _ensure_buckets() -> None:
        return None

    class _FakeKbService:
        async def get_by_id(self, requested_id: uuid.UUID):  # noqa: ANN201
            return SimpleNamespace(id=requested_id)

    class _FakeMaterialService:
        async def get_by_id(self, requested_id: uuid.UUID):  # noqa: ANN201
            assert requested_id == material_id
            return SimpleNamespace(
                id=material_id,
                kb_id=kb_id,
                source_type=SourceType.UPLOAD,
                uri=f"minio://uploads/{object_name}",
                mime_type="application/pdf",
            )

    response = await download_material(
        kb_service=_FakeKbService(),
        service=_FakeMaterialService(),
        kb_id=kb_id,
        material_id=material_id,
        resources=SimpleNamespace(
            object_storage=SimpleNamespace(
                ensure_buckets=_ensure_buckets,
                exists=_exists,
                iter_bytes=_iter_bytes,
            )
        ),
    )

    assert isinstance(response, StreamingResponse)
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert body == b"ab"
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"] == 'attachment; filename="report.pdf"'
    assert exists_calls == [("uploads", object_name)]
    assert iter_calls == [("uploads", object_name)]


@pytest.mark.asyncio
async def test_download_material_rejects_non_upload_source() -> None:
    download_material = getattr(materials_endpoint, "download_material", None)
    assert download_material is not None, "missing materials.download_material endpoint"

    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()

    class _FakeKbService:
        async def get_by_id(self, requested_id: uuid.UUID):  # noqa: ANN201
            return SimpleNamespace(id=requested_id)

    class _FakeMaterialService:
        async def get_by_id(self, requested_id: uuid.UUID):  # noqa: ANN201
            assert requested_id == material_id
            return SimpleNamespace(
                id=material_id,
                kb_id=kb_id,
                source_type=SourceType.URL,
                uri="https://example.com/doc",
                mime_type="text/html",
            )

    with pytest.raises(HTTPException) as exc_info:
        await download_material(
            kb_service=_FakeKbService(),
            service=_FakeMaterialService(),
            kb_id=kb_id,
            material_id=material_id,
            resources=SimpleNamespace(object_storage=SimpleNamespace()),
        )

    assert exc_info.value.status_code == 400


def test_export_create_request_rejects_extra_target_fields() -> None:
    with pytest.raises(ValidationError):
        ExportCreateRequest(
            type=ExportType.CHAT,
            run_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
        )

    with pytest.raises(ValidationError):
        ExportCreateRequest(
            type=ExportType.RESEARCH,
            run_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
        )

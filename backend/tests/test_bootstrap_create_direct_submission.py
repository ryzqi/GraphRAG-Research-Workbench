from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.kb_bootstrap_job import KBBootstrapJob, KBBootstrapJobStatus
from app.models.source_material import SourceMaterial
from app.schemas.ingestion_batches import IngestionBatchSubmitResponse
from app.schemas.kb_bootstrap_jobs import (
    BootstrapManifestFileEntry,
    BootstrapManifestTextEntry,
    BootstrapSubmissionCreateRequest,
)
from app.services.kb_bootstrap_job_service import KBBootstrapJobService


class _FakeSession:
    def __init__(self, *, kb, jobs: dict[uuid.UUID, KBBootstrapJob] | None = None) -> None:
        self.kb = kb
        self.jobs = dict(jobs or {})
        self.materials: dict[uuid.UUID, object] = {}
        self.added: list[object] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.refresh_calls: list[object] = []

    async def get(self, model, key):
        if model.__name__ == "KnowledgeBase":
            return self.kb if key == self.kb.id else None
        if model is KBBootstrapJob:
            return self.jobs.get(key)
        if model is SourceMaterial:
            return self.materials.get(key)
        return None

    def add(self, value) -> None:
        self.added.append(value)
        if isinstance(value, KBBootstrapJob):
            self.jobs[value.id] = value
        if isinstance(value, SourceMaterial):
            self.materials[value.id] = value

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def refresh(self, value) -> None:
        self.refresh_calls.append(value)

    async def execute(self, _stmt):
        raise AssertionError("unexpected execute call")


def _submit_response(*, kb_id: uuid.UUID) -> IngestionBatchSubmitResponse:
    return IngestionBatchSubmitResponse(
        batch_id=uuid.uuid4(),
        kb_id=kb_id,
        status="queued",
        is_bootstrap=True,
        config_snapshot_id=uuid.uuid4(),
        config_version=1,
        total_docs=1,
        accepted_docs=1,
        failed_docs=0,
        entry_errors=[],
    )


@pytest.mark.asyncio
async def test_create_submission_without_file_entries_submits_manifest_directly() -> None:
    kb = SimpleNamespace(id=uuid.uuid4(), index_config={})
    session = _FakeSession(kb=kb)
    celery = Mock()
    service = KBBootstrapJobService(session, celery=celery)
    service._submit_manifest_directly = AsyncMock(return_value=_submit_response(kb_id=kb.id))

    result = await service.create_submission(
        req=BootstrapSubmissionCreateRequest(
            kb_id=kb.id,
            entries=[BootstrapManifestTextEntry(text="direct submit")],
        ),
        request_id=None,
        requested_by="tester",
    )

    assert result.job is None
    assert result.batch is not None
    assert result.batch.kb_id == kb.id
    assert session.added == []
    service._submit_manifest_directly.assert_awaited_once()
    celery.send_task.assert_not_called()


@pytest.mark.asyncio
async def test_create_submission_with_file_entries_keeps_upload_job_path() -> None:
    kb = SimpleNamespace(id=uuid.uuid4(), index_config={})
    session = _FakeSession(kb=kb)
    celery = Mock()
    service = KBBootstrapJobService(session, celery=celery)
    service._submit_manifest_directly = AsyncMock()

    result = await service.create_submission(
        req=BootstrapSubmissionCreateRequest(
            kb_id=kb.id,
            entries=[
                BootstrapManifestFileEntry(
                    filename="demo.md",
                    size_bytes=16,
                    content_type="text/markdown",
                )
            ],
        ),
        request_id=None,
        requested_by="tester",
    )

    assert result.job is not None
    assert result.batch is None
    assert result.job.status == KBBootstrapJobStatus.QUEUED_UPLOAD
    assert any(isinstance(item, KBBootstrapJob) for item in session.added)
    service._submit_manifest_directly.assert_not_awaited()
    celery.send_task.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_submission_submits_manifest_directly_without_worker_hop() -> None:
    kb_id = uuid.uuid4()
    job_id = uuid.uuid4()
    material_id = uuid.uuid4()
    job = KBBootstrapJob(
        id=job_id,
        kb_id=kb_id,
        status=KBBootstrapJobStatus.QUEUED_UPLOAD,
        requested_by="tester",
        total_entries=1,
        payload_entries=[
            {
                "source_type": "file",
                "entry_id": "entry_1",
                "title": "demo.md",
                "material_id": str(material_id),
            }
        ],
        upload_manifest=[
            {
                "entry_id": "entry_1",
                "title": "demo.md",
                "filename": "demo.md",
                "content_type": "text/markdown",
                "size_bytes": 16,
                "sha256": None,
                "material_id": str(material_id),
                "bucket": "uploads",
                "object_key": f"{kb_id}/{material_id}/demo.md",
                "upload_status": "uploaded",
            }
        ],
    )
    session = _FakeSession(
        kb=SimpleNamespace(id=kb_id, index_config={}),
        jobs={job_id: job},
    )
    celery = Mock()
    service = KBBootstrapJobService(session, celery=celery)
    service._validate_upload_manifest = AsyncMock(
        return_value=(service._normalize_upload_manifest(job.upload_manifest), [])
    )
    service._get_submission_for_update = AsyncMock(return_value=job)
    service._submit_manifest_directly = AsyncMock(return_value=_submit_response(kb_id=kb_id))

    finalized = await service.finalize_submission(job_id=job_id)

    assert finalized is job
    assert finalized.status == KBBootstrapJobStatus.COMPLETED
    assert finalized.batch_id is not None
    assert finalized.accepted_entries == 1
    assert finalized.failed_entries == 0
    assert finalized.progress_message == "批次已创建，文档处理中"
    service._submit_manifest_directly.assert_awaited_once()
    celery.send_task.assert_not_called()

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.ingestion_batch import IngestionBatchStatus
from app.models.knowledge_base import KnowledgeBase
from app.schemas.ingestion_batches import ManifestSourceType, ManifestTextEntry
from app.services.ingestion_batch_service import IngestionBatchService, _PreparedEntry


class _FakeSession:
    def __init__(self, kb: SimpleNamespace) -> None:
        self._kb = kb

    async def get(self, model, _key):  # noqa: ANN001
        if model is KnowledgeBase:
            return self._kb
        return None


@pytest.mark.asyncio
async def test_submit_manifest_keeps_success_when_dispatch_trigger_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id = uuid.uuid4()
    fake_kb = SimpleNamespace(id=kb_id)
    service = IngestionBatchService(_FakeSession(fake_kb))

    async def _fake_prepare_entries(**_kwargs) -> list[_PreparedEntry]:
        return [
            _PreparedEntry(
                entry_id="entry_1",
                source_type=ManifestSourceType.TEXT,
                title="doc",
                payload={"text": "hello"},
                fingerprint="fingerprint_1",
            )
        ]

    batch_id = uuid.uuid4()
    config_snapshot_id = uuid.uuid4()
    fake_batch = SimpleNamespace(
        id=batch_id,
        kb_id=kb_id,
        status=IngestionBatchStatus.PROCESSING,
        is_bootstrap=False,
        config_snapshot_id=config_snapshot_id,
        config_version=1,
        total_docs=1,
    )
    fake_doc = SimpleNamespace(id=uuid.uuid4())

    async def _fake_create_batch_with_retry(**_kwargs):
        return fake_batch, [fake_doc]

    monkeypatch.setattr(service, "_prepare_entries", _fake_prepare_entries)
    monkeypatch.setattr(service, "_create_batch_with_retry", _fake_create_batch_with_retry)
    monkeypatch.setattr(
        service,
        "_trigger_outbox_dispatch",
        lambda: (_ for _ in ()).throw(RuntimeError("celery down")),
    )

    response = await service.submit_manifest(
        kb_id=kb_id,
        entries=[
            ManifestTextEntry(
                source_type=ManifestSourceType.TEXT,
                text="hello",
                title="doc",
                entry_id="entry_1",
            )
        ],
    )

    assert response.batch_id == batch_id
    assert response.kb_id == kb_id
    assert response.accepted_docs == 1
    assert response.failed_docs == 0


def test_outbox_migration_exists() -> None:
    migration_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("alembic/versions").glob("*.py"))
    )
    assert "ingestion_task_outbox" in migration_text
    assert "ingestion_task_outbox_status" in migration_text

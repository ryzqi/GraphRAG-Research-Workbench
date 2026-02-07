from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services import knowledge_base_service as kb_service_mod
from app.services.knowledge_base_service import KnowledgeBaseService


class _DummySession:
    def __init__(self, kb: object | None) -> None:
        self._kb = kb
        self.deleted: list[object] = []
        self.delete_called = False
        self.flush_called = False
        self.commit_called = False
        self.rollback_called = False

    async def get(self, _model: object, _id: object) -> object | None:
        return self._kb

    async def delete(self, obj: object) -> None:
        self.delete_called = True
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flush_called = True

    async def commit(self) -> None:
        self.commit_called = True

    async def rollback(self) -> None:
        self.rollback_called = True


class _DummyMilvus:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.deleted_kb_ids: list[str] = []
        self.closed = False

    async def delete_by_kb_id(self, kb_id: str) -> None:
        self.deleted_kb_ids.append(kb_id)
        if self.should_fail:
            raise RuntimeError("milvus cleanup failed")

    async def aclose(self) -> None:
        self.closed = True


class _DummyStorage:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: list[tuple[str, str]] = []

    async def remove_by_prefix(self, *, bucket: str, prefix: str) -> int:
        self.calls.append((bucket, prefix))
        if self.should_fail:
            raise RuntimeError("storage cleanup failed")
        return 1


@pytest.mark.asyncio
async def test_delete_cleans_milvus_and_minio_before_db_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id = uuid.uuid4()
    kb = SimpleNamespace(id=kb_id)
    session = _DummySession(kb)
    milvus = _DummyMilvus()
    storage = _DummyStorage()

    monkeypatch.setattr(kb_service_mod, "create_milvus_client", lambda: milvus)
    monkeypatch.setattr(kb_service_mod, "ObjectStorage", lambda: storage)
    monkeypatch.setattr(
        kb_service_mod,
        "get_settings",
        lambda: SimpleNamespace(minio_bucket_uploads="kb-uploads"),
    )

    service = KnowledgeBaseService(session)  # type: ignore[arg-type]
    result = await service.delete(kb_id)

    assert result is True
    assert milvus.deleted_kb_ids == [str(kb_id)]
    assert milvus.closed is True
    assert storage.calls == [("kb-uploads", f"{kb_id}/")]
    assert session.deleted == [kb]
    assert session.delete_called is True
    assert session.flush_called is True
    assert session.commit_called is True
    assert session.rollback_called is False


@pytest.mark.asyncio
async def test_delete_returns_false_without_cleanup_when_kb_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _DummySession(None)
    milvus = _DummyMilvus()
    storage = _DummyStorage()

    monkeypatch.setattr(kb_service_mod, "create_milvus_client", lambda: milvus)
    monkeypatch.setattr(kb_service_mod, "ObjectStorage", lambda: storage)

    service = KnowledgeBaseService(session)  # type: ignore[arg-type]
    result = await service.delete(uuid.uuid4())

    assert result is False
    assert milvus.deleted_kb_ids == []
    assert milvus.closed is False
    assert storage.calls == []
    assert session.delete_called is False
    assert session.flush_called is False
    assert session.commit_called is False
    assert session.rollback_called is False


@pytest.mark.asyncio
async def test_delete_rolls_back_when_milvus_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id = uuid.uuid4()
    session = _DummySession(SimpleNamespace(id=kb_id))
    milvus = _DummyMilvus(should_fail=True)
    storage = _DummyStorage()

    monkeypatch.setattr(kb_service_mod, "create_milvus_client", lambda: milvus)
    monkeypatch.setattr(kb_service_mod, "ObjectStorage", lambda: storage)
    monkeypatch.setattr(
        kb_service_mod,
        "get_settings",
        lambda: SimpleNamespace(minio_bucket_uploads="kb-uploads"),
    )

    service = KnowledgeBaseService(session)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="milvus cleanup failed"):
        await service.delete(kb_id)

    assert milvus.closed is True
    assert storage.calls == []
    assert session.delete_called is True
    assert session.flush_called is True
    assert session.commit_called is False
    assert session.rollback_called is True


@pytest.mark.asyncio
async def test_delete_rolls_back_when_storage_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id = uuid.uuid4()
    session = _DummySession(SimpleNamespace(id=kb_id))
    milvus = _DummyMilvus()
    storage = _DummyStorage(should_fail=True)

    monkeypatch.setattr(kb_service_mod, "create_milvus_client", lambda: milvus)
    monkeypatch.setattr(kb_service_mod, "ObjectStorage", lambda: storage)
    monkeypatch.setattr(
        kb_service_mod,
        "get_settings",
        lambda: SimpleNamespace(minio_bucket_uploads="kb-uploads"),
    )

    service = KnowledgeBaseService(session)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="storage cleanup failed"):
        await service.delete(kb_id)

    assert milvus.deleted_kb_ids == [str(kb_id)]
    assert milvus.closed is True
    assert storage.calls == [("kb-uploads", f"{kb_id}/")]
    assert session.delete_called is True
    assert session.flush_called is True
    assert session.commit_called is False
    assert session.rollback_called is True
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from sqlalchemy.exc import IntegrityError

from app.schemas.knowledge_bases import (
    IndexConfig,
    KnowledgeBaseCreate,
    KnowledgeBaseIndexConfigUpdateRequest,
    KnowledgeBaseStatusFilter,
)


def _build_kb(kb_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=kb_id,
        name="kb",
        description=None,
        tags=None,
        status="active",
        readiness="ready",
        readiness_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        current_config_version=1,
        index_config=IndexConfig().model_dump(mode="json"),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_create_knowledge_base_maps_unique_integrity_error_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.endpoints import knowledge_bases as kb_ep

    class _Db:
        def __init__(self) -> None:
            self.rollback_called = False

        async def rollback(self) -> None:
            self.rollback_called = True

    class _KbService:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_name(self, _name: str) -> object | None:
            return None

        async def create(self, **_kwargs: object) -> object:
            raise IntegrityError(
                "insert into knowledge_bases",
                {"name": "dup"},
                Exception(
                    'duplicate key value violates unique constraint "knowledge_bases_name_key"'
                ),
            )

    monkeypatch.setattr(kb_ep, "KnowledgeBaseService", _KbService)

    db = _Db()
    with pytest.raises(HTTPException) as exc:
        await kb_ep.create_knowledge_base(
            db=db,
            body=KnowledgeBaseCreate(name="dup", description=None, tags=None),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "KB_NAME_EXISTS"
    assert db.rollback_called is True


@pytest.mark.asyncio
async def test_create_knowledge_base_returns_409_when_name_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.endpoints import knowledge_bases as kb_ep

    class _KbService:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_name(self, _name: str) -> object | None:
            return _build_kb(uuid.uuid4())

    monkeypatch.setattr(kb_ep, "KnowledgeBaseService", _KbService)

    with pytest.raises(HTTPException) as exc:
        await kb_ep.create_knowledge_base(
            db=object(),
            body=KnowledgeBaseCreate(name="dup", description=None, tags=None),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "KB_NAME_EXISTS"


@pytest.mark.asyncio
async def test_create_knowledge_base_uses_default_index_config_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.endpoints import knowledge_bases as kb_ep

    kb_id = uuid.uuid4()
    captured: dict[str, object] = {}

    class _KbService:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_name(self, _name: str) -> object | None:
            return None

        async def create(self, **kwargs: object) -> object:
            captured.update(kwargs)
            kb = _build_kb(kb_id)
            kb.name = str(kwargs["name"])
            kb.description = kwargs["description"]
            kb.tags = kwargs["tags"]
            kb.index_config = kwargs["index_config"]
            return kb

    monkeypatch.setattr(kb_ep, "KnowledgeBaseService", _KbService)

    result = await kb_ep.create_knowledge_base(
        db=object(),
        body=KnowledgeBaseCreate(name="new-kb", description="desc", tags=["tag"]),
    )

    assert captured["name"] == "new-kb"
    assert captured["description"] == "desc"
    assert captured["tags"] == ["tag"]
    assert captured["index_config"] == IndexConfig().model_dump(mode="json")
    assert result.id == kb_id


@pytest.mark.asyncio
async def test_list_knowledge_bases_status_all_uses_unfiltered_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.endpoints import knowledge_bases as kb_ep

    captured: dict[str, object] = {}
    kb_id = uuid.uuid4()

    class _KbService:
        def __init__(self, _db: object) -> None:
            pass

        async def list_page(
            self,
            *,
            skip: int = 0,
            limit: int = 100,
            status: object | None = None,
            readiness: object | None = None,
        ) -> tuple[list[object], int]:
            captured["skip"] = skip
            captured["limit"] = limit
            captured["status"] = status
            captured["readiness"] = readiness
            return [_build_kb(kb_id)], 2

    monkeypatch.setattr(kb_ep, "KnowledgeBaseService", _KbService)

    result = await kb_ep.list_knowledge_bases(
        db=object(),
        skip=0,
        limit=10,
        status=KnowledgeBaseStatusFilter.ALL,
    )

    assert captured == {"skip": 0, "limit": 10, "status": None, "readiness": None}
    assert len(result.items) == 1
    assert result.items[0].id == kb_id
    assert result.page.total == 2
    assert result.page.has_more is True


@pytest.mark.asyncio
async def test_update_index_config_refreshes_kb_before_serializing_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.endpoints import knowledge_bases as kb_ep

    kb_id = uuid.uuid4()
    stale_updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fresh_updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    kb = _build_kb(kb_id)
    kb.updated_at = stale_updated_at

    class _Db:
        def __init__(self) -> None:
            self.refresh_calls = 0

        async def refresh(self, obj: object) -> None:
            self.refresh_calls += 1
            if obj is kb:
                kb.updated_at = fresh_updated_at

    class _KbService:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _kb_id: uuid.UUID) -> object | None:
            return kb

    class _IndexRebuildService:
        def __init__(self, _db: object) -> None:
            pass

        async def create_job(self, *, kb: object, index_config: dict) -> object:
            assert kb is not None
            assert isinstance(index_config, dict)
            return SimpleNamespace(
                id=uuid.uuid4(),
                kb_id=kb_id,
                status="queued",
                error_message=None,
                stats=None,
                created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                started_at=None,
                finished_at=None,
            )

    monkeypatch.setattr(kb_ep, "KnowledgeBaseService", _KbService)
    monkeypatch.setattr(kb_ep, "IndexRebuildService", _IndexRebuildService)

    body = KnowledgeBaseIndexConfigUpdateRequest(
        index_config=IndexConfig.model_validate({"chunking": {"sliding_window": {"chunk_size": 600}}})
    )
    db = _Db()

    result = await kb_ep.update_index_config(
        db=db,
        kb_id=kb_id,
        body=body,
        response=Response(),
    )

    assert db.refresh_calls == 1
    assert result.knowledge_base.updated_at == fresh_updated_at
    assert result.rebuild_job is not None


@pytest.mark.asyncio
async def test_update_index_config_returns_200_without_rebuild_when_config_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.endpoints import knowledge_bases as kb_ep

    kb = _build_kb(uuid.uuid4())

    class _KbService:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _kb_id: uuid.UUID) -> object | None:
            return kb

    class _IndexRebuildService:
        def __init__(self, _db: object) -> None:
            pass

        async def create_job(self, *, kb: object, index_config: dict) -> object:
            raise AssertionError("rebuild should not be triggered for unchanged config")

    monkeypatch.setattr(kb_ep, "KnowledgeBaseService", _KbService)
    monkeypatch.setattr(kb_ep, "IndexRebuildService", _IndexRebuildService)

    body = KnowledgeBaseIndexConfigUpdateRequest(
        index_config=IndexConfig.model_validate(kb.index_config)
    )
    response = Response()

    result = await kb_ep.update_index_config(
        db=object(),
        kb_id=kb.id,
        body=body,
        response=response,
    )

    assert response.status_code == 200
    assert result.rebuild_job is None
    assert result.knowledge_base.id == kb.id


@pytest.mark.asyncio
async def test_delete_knowledge_base_requires_confirm() -> None:
    from app.api.v1.endpoints import knowledge_bases as kb_ep

    with pytest.raises(HTTPException) as exc:
        await kb_ep.delete_knowledge_base(db=object(), kb_id=uuid.uuid4(), confirm=False)

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "CONFIRM_REQUIRED"


@pytest.mark.asyncio
async def test_delete_knowledge_base_calls_service_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1.endpoints import knowledge_bases as kb_ep

    kb_id = uuid.uuid4()
    deleted: list[uuid.UUID] = []

    class _KbService:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _kb_id: uuid.UUID) -> object | None:
            return _build_kb(_kb_id)

        async def delete(self, _kb_id: uuid.UUID) -> bool:
            deleted.append(_kb_id)
            return True

    monkeypatch.setattr(kb_ep, "KnowledgeBaseService", _KbService)

    await kb_ep.delete_knowledge_base(db=object(), kb_id=kb_id, confirm=True)
    assert deleted == [kb_id]


@pytest.mark.asyncio
async def test_delete_knowledge_base_not_found_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.endpoints import knowledge_bases as kb_ep

    class _KbService:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _kb_id: uuid.UUID) -> object | None:
            return None

    monkeypatch.setattr(kb_ep, "KnowledgeBaseService", _KbService)

    with pytest.raises(HTTPException) as exc:
        await kb_ep.delete_knowledge_base(db=object(), kb_id=uuid.uuid4(), confirm=True)

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "KB_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_knowledge_base_not_found_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1.endpoints import knowledge_bases as kb_ep

    class _KbService:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _kb_id: uuid.UUID) -> object | None:
            return None

    monkeypatch.setattr(kb_ep, "KnowledgeBaseService", _KbService)

    with pytest.raises(HTTPException) as exc:
        await kb_ep.get_knowledge_base(db=object(), kb_id=uuid.uuid4())

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "KB_NOT_FOUND"
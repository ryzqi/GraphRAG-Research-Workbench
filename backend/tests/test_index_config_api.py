from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.api import api_router
from app.core.errors import register_exception_handlers
from app.core.middleware.request_id import RequestIdMiddleware
from app.db.session import get_db_session
from app.schemas.index_rebuilds import IndexRebuildStatus
from app.schemas.knowledge_bases import IndexConfig
from app.services.index_rebuild_service import IndexRebuildService
from app.services.knowledge_base_service import KnowledgeBaseService


def _build_client() -> tuple[TestClient, dict[str, str]]:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    async def _override_db_session():
        yield SimpleNamespace()

    app.dependency_overrides[get_db_session] = _override_db_session

    client = TestClient(app)
    headers = {"X-Request-ID": "rid_test"}
    return client, headers


def test_index_config_parent_child_normalizes_contextual() -> None:
    config = IndexConfig.model_validate(
        {
            "chunking": {"general_strategy": "parent_child"},
            "contextual": {
                "enabled": True,
                "timeout_seconds": 15,
                "max_tokens": 128,
                "concurrency": 3,
            },
        }
    )

    assert config.contextual.enabled is False


def test_patch_kb_rejects_index_config(monkeypatch) -> None:
    client, headers = _build_client()
    kb_id = str(uuid.uuid4())
    payload = {"index_config": IndexConfig().model_dump(mode="json")}

    res = client.patch(f"/api/v1/knowledge-bases/{kb_id}", headers=headers, json=payload)

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INDEX_CONFIG_NOT_ALLOWED"


def test_create_kb_normalizes_parent_child_contextual(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    kb_id = uuid.uuid4()
    payload = IndexConfig.model_validate(
        {
            "chunking": {"general_strategy": "parent_child"},
            "contextual": {
                "enabled": True,
                "timeout_seconds": 15,
                "max_tokens": 128,
                "concurrency": 3,
            },
        }
    ).model_dump(mode="json")

    async def _fake_get_by_name(self, _name: str):
        return None

    async def _fake_create(self, *, name, description=None, tags=None, index_config=None):
        assert index_config is not None
        assert index_config["contextual"]["enabled"] is False
        return SimpleNamespace(
            id=kb_id,
            name=name,
            description=description,
            tags=tags,
            status="active",
            index_config=index_config,
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(KnowledgeBaseService, "get_by_name", _fake_get_by_name)
    monkeypatch.setattr(KnowledgeBaseService, "create", _fake_create)

    client, headers = _build_client()
    res = client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "kb", "index_config": payload},
    )

    assert res.status_code == 201
    body = res.json()
    assert body["index_config"]["contextual"]["enabled"] is False


def test_put_index_config_returns_rebuild_job(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    kb_id = uuid.uuid4()
    job_id = uuid.uuid4()

    kb = SimpleNamespace(
        id=kb_id,
        name="kb",
        description=None,
        tags=None,
        status="active",
        index_config=IndexConfig().model_dump(mode="json"),
        created_at=now,
        updated_at=now,
    )

    job = SimpleNamespace(
        id=job_id,
        kb_id=kb_id,
        status=IndexRebuildStatus.QUEUED,
        error_message=None,
        stats=None,
        created_at=now,
        started_at=None,
        finished_at=None,
    )

    async def _fake_get_by_id(self, _kb_id):
        return kb

    async def _fake_create_job(self, *, kb, index_config):
        return job

    monkeypatch.setattr(KnowledgeBaseService, "get_by_id", _fake_get_by_id)
    monkeypatch.setattr(IndexRebuildService, "create_job", _fake_create_job)

    client, headers = _build_client()
    res = client.put(
        f"/api/v1/knowledge-bases/{kb_id}/index-config",
        headers=headers,
        json={"index_config": IndexConfig().model_dump(mode="json")},
    )

    assert res.status_code == 202
    body = res.json()
    assert body["knowledge_base"]["id"] == str(kb_id)
    assert body["rebuild_job"]["id"] == str(job_id)


def test_put_index_config_idempotent_returns_no_job(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    kb_id = uuid.uuid4()
    config = IndexConfig().model_dump(mode="json")

    kb = SimpleNamespace(
        id=kb_id,
        name="kb",
        description=None,
        tags=None,
        status="active",
        index_config=config,
        created_at=now,
        updated_at=now,
    )

    async def _fake_get_by_id(self, _kb_id):
        return kb

    async def _fake_create_job(self, *, kb, index_config):
        raise AssertionError("create_job should not be called for idempotent update")

    monkeypatch.setattr(KnowledgeBaseService, "get_by_id", _fake_get_by_id)
    monkeypatch.setattr(IndexRebuildService, "create_job", _fake_create_job)

    client, headers = _build_client()
    res = client.put(
        f"/api/v1/knowledge-bases/{kb_id}/index-config",
        headers=headers,
        json={"index_config": config},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["knowledge_base"]["id"] == str(kb_id)
    assert body["rebuild_job"] is None


def test_get_index_rebuild_job_contract(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    job_id = uuid.uuid4()
    job = SimpleNamespace(
        id=job_id,
        kb_id=uuid.uuid4(),
        status=IndexRebuildStatus.RUNNING,
        error_message=None,
        stats=None,
        created_at=now,
        started_at=now,
        finished_at=None,
    )

    async def _fake_get_by_id(self, _job_id):
        return job

    monkeypatch.setattr(IndexRebuildService, "get_by_id", _fake_get_by_id)

    client, headers = _build_client()
    res = client.get(f"/api/v1/index-rebuilds/{job_id}", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == str(job_id)
    assert body["status"] == "running"

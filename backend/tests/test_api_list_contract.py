from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.api import api_router
from app.api.v1.endpoints import health as health_endpoints
from app.core.errors import register_exception_handlers
from app.core.middleware.request_id import RequestIdMiddleware
from app.core.settings import get_settings
from app.db.session import get_db_session
from app.schemas.extensions import ToolDescriptor, ToolExtensionRead
from app.services.extension_service import ExtensionService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.knowledge_update_service import KnowledgeUpdateService
from app.services.material_service import MaterialService


def _build_client() -> tuple[TestClient, dict[str, str]]:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    app.state.mcp_client = SimpleNamespace()

    async def _override_db_session():
        yield SimpleNamespace()

    app.dependency_overrides[get_db_session] = _override_db_session

    client = TestClient(app)
    headers = {
        "X-Request-ID": "rid_test",
        "X-Admin-Token": get_settings().admin_token,
    }
    return client, headers


def test_list_knowledge_updates_contract(monkeypatch) -> None:
    async def _fake_list_proposals_page(
        self, session, *, kb_id=None, status=None, skip=0, limit=100
    ):
        item = SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=uuid.uuid4(),
            source_run_id=uuid.uuid4(),
            summary="s",
            payload={},
            status="pending",
            created_by=None,
            reviewed_by=None,
            created_at=datetime.now(timezone.utc),
            reviewed_at=None,
        )
        items = [item]
        return items[skip : skip + limit], len(items)

    monkeypatch.setattr(KnowledgeUpdateService, "list_proposals_page", _fake_list_proposals_page)

    client, headers = _build_client()
    res = client.get("/api/v1/knowledge-updates", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body.get("items"), list)
    assert body.get("page", {}).get("total") == 1


def test_list_extensions_contract(monkeypatch) -> None:
    async def _fake_list_extensions_page(self, *, status=None, skip=0, limit=100):
        now = datetime.now(timezone.utc)
        item = ToolExtensionRead(
            id=uuid.uuid4(),
            name="ext",
            transport="http",
            endpoint="http://localhost:3000",
            status="enabled",
            scope=None,
            created_at=now,
            updated_at=now,
        )
        items = [item]
        return items[skip : skip + limit], len(items)

    monkeypatch.setattr(ExtensionService, "list_extensions_page", _fake_list_extensions_page)

    client, headers = _build_client()
    res = client.get("/api/v1/extensions", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body.get("items"), list)
    assert body.get("page", {}).get("total") == 1


def test_list_extension_tools_contract(monkeypatch) -> None:
    async def _fake_get_extension(self, extension_id):
        now = datetime.now(timezone.utc)
        return ToolExtensionRead(
            id=extension_id,
            name="ext",
            transport="http",
            endpoint="http://localhost:3000",
            status="enabled",
            scope=None,
            created_at=now,
            updated_at=now,
        )

    async def _fake_get_tools_page(self, extension_id, *, skip=0, limit=100):
        items = [
            ToolDescriptor(name="t1", description=None, input_schema=None),
            ToolDescriptor(name="t2", description="d", input_schema={}),
        ]
        return items[skip : skip + limit], len(items)

    monkeypatch.setattr(ExtensionService, "get_extension", _fake_get_extension)
    monkeypatch.setattr(ExtensionService, "get_tools_page", _fake_get_tools_page)

    client, headers = _build_client()
    ext_id = str(uuid.uuid4())
    res = client.get(f"/api/v1/extensions/{ext_id}/tools", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body.get("items"), list)
    assert body.get("page", {}).get("total") == 2


def test_list_knowledge_bases_contract(monkeypatch) -> None:
    async def _fake_list_active_page(self, *, skip=0, limit=100):
        now = datetime.now(timezone.utc)
        item = SimpleNamespace(
            id=uuid.uuid4(),
            name="kb",
            description=None,
            tags=None,
            status="active",
            created_at=now,
            updated_at=now,
        )
        items = [item]
        return items[skip : skip + limit], len(items)

    monkeypatch.setattr(KnowledgeBaseService, "list_active_page", _fake_list_active_page)

    client, headers = _build_client()
    res = client.get("/api/v1/knowledge-bases", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body.get("items"), list)
    assert body.get("page", {}).get("total") == 1


def test_list_materials_contract(monkeypatch) -> None:
    async def _fake_get_by_id(self, kb_id):
        return SimpleNamespace(id=kb_id)

    async def _fake_list_by_kb_page(self, kb_id, *, skip=0, limit=100):
        now = datetime.now(timezone.utc)
        item = SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            source_type="text",
            title="t",
            uri=None,
            mime_type=None,
            created_at=now,
            updated_at=now,
        )
        items = [item]
        return items[skip : skip + limit], len(items)

    monkeypatch.setattr(KnowledgeBaseService, "get_by_id", _fake_get_by_id)
    monkeypatch.setattr(MaterialService, "list_by_kb_page", _fake_list_by_kb_page)

    client, headers = _build_client()
    kb_id = str(uuid.uuid4())
    res = client.get(f"/api/v1/knowledge-bases/{kb_id}/materials", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body.get("items"), list)
    assert body.get("page", {}).get("total") == 1


def test_kb_name_conflict_returns_409(monkeypatch) -> None:
    async def _fake_get_by_name(self, name: str):
        return SimpleNamespace(id=uuid.uuid4(), name=name)

    monkeypatch.setattr(KnowledgeBaseService, "get_by_name", _fake_get_by_name)

    client, headers = _build_client()
    res = client.post("/api/v1/knowledge-bases", headers=headers, json={"name": "demo"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "KB_NAME_EXISTS"


def test_create_ingestion_kb_not_found_returns_404(monkeypatch) -> None:
    async def _fake_get_by_id(self, kb_id):
        return None

    monkeypatch.setattr(KnowledgeBaseService, "get_by_id", _fake_get_by_id)

    client, headers = _build_client()
    res = client.post(
        "/api/v1/ingestions",
        headers=headers,
        json={
            "kb_id": str(uuid.uuid4()),
            "material_ids": [str(uuid.uuid4())],
            "mode": "create",
        },
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "KB_NOT_FOUND"


def test_ready_503_uses_error_contract(monkeypatch) -> None:
    async def _fail():
        raise RuntimeError("boom")

    async def _ok():
        return None

    monkeypatch.setattr(health_endpoints, "_check_postgres", _fail)
    monkeypatch.setattr(health_endpoints, "_check_redis", _ok)
    monkeypatch.setattr(health_endpoints, "_check_milvus", _ok)
    monkeypatch.setattr(health_endpoints, "_check_minio", _ok)

    client, _headers = _build_client()
    res = client.get("/api/v1/ready", headers={"X-Request-ID": "rid_test"})
    assert res.status_code == 503
    body = res.json()
    assert body["error"]["code"] == "NOT_READY"
    assert "dependencies" in (body["error"].get("details") or {})


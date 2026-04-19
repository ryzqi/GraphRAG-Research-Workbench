from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest

from app.api.dependencies import services as service_deps
from app.core.settings import Settings
from app.integrations.rerank_client import RerankClient
from app.services.url_ingestion_guard import build_url_ingestion_guard
from app.services import web_search_status_service


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, web_search_api_key="test-key", **overrides)


class _DummyRerankResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"results": []}


class _UnexpectedAsyncClient:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.created = True

    async def __aenter__(self) -> "_UnexpectedAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def post(self, *args: object, **kwargs: object) -> _DummyRerankResponse:
        return _DummyRerankResponse()

    async def get(self, *args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(status_code=200, headers={})


async def test_rerank_client_requires_shared_http_client(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _UnexpectedAsyncClient)
    client = RerankClient(settings=_make_settings())

    with pytest.raises(RuntimeError, match="http_client"):
        await client.rerank(query="q", documents=["doc"])


async def test_url_ingestion_guard_requires_shared_http_client(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _UnexpectedAsyncClient)
    guard = build_url_ingestion_guard(_make_settings())

    async def _noop_assert_host_safe(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(type(guard), "_assert_host_safe", _noop_assert_host_safe)

    with pytest.raises(RuntimeError, match="http_client"):
        await guard.validate_source_url("https://example.com")


def test_build_ingestion_batch_service_uses_app_http_client(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeService:
        def __init__(self, db: object, *, http_client: object | None = None) -> None:
            captured["db"] = db
            captured["http_client"] = http_client

    monkeypatch.setattr(service_deps, "IngestionBatchService", _FakeService)

    db = object()
    resources = SimpleNamespace(http_client=object())
    service_deps.build_ingestion_batch_service(db=db, resources=resources)

    assert captured["db"] is db
    assert captured["http_client"] is resources.http_client


def test_build_material_service_uses_app_http_client(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeService:
        def __init__(self, db: object, *, http_client: object | None = None) -> None:
            captured["db"] = db
            captured["http_client"] = http_client

    monkeypatch.setattr(service_deps, "MaterialService", _FakeService)

    db = object()
    resources = SimpleNamespace(http_client=object())
    service_deps.build_material_service(db=db, resources=resources)

    assert captured["db"] is db
    assert captured["http_client"] is resources.http_client


def test_build_kb_bootstrap_job_service_uses_app_http_client(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeService:
        def __init__(self, db: object, *, http_client: object | None = None) -> None:
            captured["db"] = db
            captured["http_client"] = http_client

    monkeypatch.setattr(service_deps, "KBBootstrapJobService", _FakeService)

    db = object()
    resources = SimpleNamespace(http_client=object())
    service_deps.build_kb_bootstrap_job_service(db=db, resources=resources)

    assert captured["db"] is db
    assert captured["http_client"] is resources.http_client


async def test_open_ingestion_batch_service_scope_uses_app_http_client(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeService:
        def __init__(self, db: object, *, http_client: object | None = None) -> None:
            captured["db"] = db
            captured["http_client"] = http_client

    @asynccontextmanager
    async def _fake_open_service_scope(*, resources, factory):
        db = object()
        yield db, factory(db)

    monkeypatch.setattr(service_deps, "IngestionBatchService", _FakeService)
    monkeypatch.setattr(service_deps, "_open_service_scope", _fake_open_service_scope)

    resources = SimpleNamespace(http_client=object(), engine=object())
    async with service_deps.open_ingestion_batch_service_scope(resources=resources):
        pass

    assert captured["http_client"] is resources.http_client


async def test_get_web_search_status_passes_shared_http_client(monkeypatch) -> None:
    captured: dict[str, object] = {}
    http_client = object()

    def _fake_build_search_providers(*, settings: Settings, http_client: object | None = None):
        captured["settings"] = settings
        captured["http_client"] = http_client
        return []

    monkeypatch.setattr(
        web_search_status_service,
        "build_search_providers",
        _fake_build_search_providers,
    )
    monkeypatch.setattr(
        web_search_status_service,
        "_cached_status",
        None,
    )
    monkeypatch.setattr(
        web_search_status_service,
        "_cached_expires_at",
        0.0,
    )

    await web_search_status_service.get_web_search_status(
        settings=_make_settings(),
        http_client=http_client,
    )

    assert captured["http_client"] is http_client

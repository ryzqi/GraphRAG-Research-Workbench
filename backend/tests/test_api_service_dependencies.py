from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from app.api.dependencies.app_resources import get_app_resources
from app.api.dependencies.services import (
    build_extension_service,
    build_export_service,
    build_knowledge_base_service,
    build_queue_health_service,
    get_research_service,
)
from app.bootstrap.app_resources import AppResources
from app.integrations.llm_client import LLMClient
from app.services.extension_service import ExtensionService
from app.services.export_service import ExportService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.queue_health_service import QueueHealthService
from app.services.research_service import ResearchService


class _DummyDb:
    pass


def _build_resources() -> AppResources:
    return AppResources(
        engine=object(),
        http_client=object(),
        embedding_http_client=object(),
        llm_client=cast(LLMClient, object()),
        milvus_client=object(),
        embedding_client=object(),
        rerank_client=object(),
        redis=object(),
    )


def test_get_app_resources_reads_typed_resources_from_request_state() -> None:
    resources = _build_resources()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(resources=resources)))

    assert get_app_resources(request) is resources


def test_build_queue_health_service_uses_resources_redis() -> None:
    db = _DummyDb()
    resources = _build_resources()

    service = build_queue_health_service(db=db, resources=resources)

    assert isinstance(service, QueueHealthService)
    assert service._db is db
    assert service._redis is resources.redis


def test_get_research_service_uses_override_factory_when_present() -> None:
    db = _DummyDb()
    sentinel = cast(ResearchService, object())
    captured: dict[str, object] = {}

    def _factory(*, db: object, request: object) -> ResearchService:
        captured["db"] = db
        captured["request"] = request
        return sentinel

    resources = _build_resources()
    resources.research_service_factory = _factory
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(resources=resources)))

    service = get_research_service(db=db, request=request, resources=resources)

    assert service is sentinel
    assert captured == {"db": db, "request": request}


def test_simple_service_builders_return_expected_types() -> None:
    db = _DummyDb()

    assert isinstance(build_extension_service(db=db), ExtensionService)
    assert isinstance(build_knowledge_base_service(db=db), KnowledgeBaseService)
    assert isinstance(build_export_service(), ExportService)

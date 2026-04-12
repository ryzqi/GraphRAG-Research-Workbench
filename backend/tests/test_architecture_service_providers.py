from __future__ import annotations

from typing import cast

from app.api.dependencies.services import (
    build_extension_service,
    build_queue_health_service,
    get_research_service,
)
from app.bootstrap.app_resources import AppResources
from app.integrations.llm_client import LLMClient
from app.repositories.extension_repository import ExtensionRepository
from app.repositories.queue_health_repository import QueueHealthRepository
from app.repositories.research_session_repository import ResearchSessionRepository


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


def test_build_extension_service_injects_repository() -> None:
    db = _DummyDb()

    service = build_extension_service(db=db)

    assert isinstance(service._repository, ExtensionRepository)
    assert service._repository._db is db


def test_build_queue_health_service_injects_repository() -> None:
    db = _DummyDb()
    resources = _build_resources()

    service = build_queue_health_service(db=db, resources=resources)

    assert isinstance(service._repository, QueueHealthRepository)
    assert service._repository._db is db


def test_get_research_service_injects_session_repository() -> None:
    db = _DummyDb()
    resources = _build_resources()
    request = cast(object, object())

    service = get_research_service(db=db, request=request, resources=resources)

    assert isinstance(service._session_repository, ResearchSessionRepository)
    assert service._session_repository._db is db

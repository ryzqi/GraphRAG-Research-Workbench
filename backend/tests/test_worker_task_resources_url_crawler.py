from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.settings import Settings
from app.models.knowledge_base import KnowledgeBase
from app.models.source_material import SourceMaterial, SourceType
from app.services.parsing.errors import ParseError
import app.worker.task_resources as task_resources
import app.worker.tasks.ingestion_batches as ingestion_batches


def _settings() -> Settings:
    return Settings(_env_file=None)


class _FakeScalarResult:
    def __init__(self, scalar: object) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar


class _FakeSession:
    def __init__(self, *, material: SourceMaterial, kb: object) -> None:
        self._material = material
        self._kb = kb

    async def get(self, model, _id):  # type: ignore[no-untyped-def]
        if model is SourceMaterial:
            return self._material
        if model is KnowledgeBase:
            return self._kb
        raise AssertionError(f"unexpected model: {model}")

    async def execute(self, _stmt):
        return _FakeScalarResult(None)


@pytest.mark.asyncio
async def test_managed_task_resources_reuses_single_url_crawler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []
    closed: list[object] = []

    async def fake_create_url_crawler(*, settings: Settings) -> object:
        del settings
        crawler = object()
        created.append(crawler)
        return crawler

    async def fake_close_url_crawler(crawler: object | None) -> None:
        if crawler is not None:
            closed.append(crawler)

    monkeypatch.setattr(
        task_resources, "create_url_crawler", fake_create_url_crawler, raising=False
    )
    monkeypatch.setattr(
        task_resources, "close_url_crawler", fake_close_url_crawler, raising=False
    )

    async with task_resources.managed_task_resources(
        settings=_settings(),
        with_engine=False,
        with_http=False,
        with_redis=False,
        with_milvus=False,
    ) as resources:
        getter = getattr(resources, "get_url_crawler", None)
        assert callable(getter)
        first = await getter()
        second = await getter()
        assert first is second

    assert len(created) == 1
    assert closed == [created[0]]


@pytest.mark.asyncio
async def test_process_doc_passes_worker_url_crawler_to_parse_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material_id = uuid4()
    kb_id = uuid4()
    crawler = object()
    material = SourceMaterial(
        id=material_id,
        kb_id=kb_id,
        source_type=SourceType.URL,
        title="示例",
        uri="https://example.com/article",
        mime_type=None,
        content_hash=None,
        metadata_=None,
    )
    kb = SimpleNamespace(
        id=kb_id,
        index_config={
            "chunking": {"general_strategy": "markdown_heading"},
            "contextual": {"enabled": False, "max_tokens": 192, "concurrency": 1},
        },
    )
    session = _FakeSession(material=material, kb=kb)

    @asynccontextmanager
    async def session_scope():
        yield session

    async def fake_parse_material(
        material_arg: SourceMaterial,
        *,
        settings: Settings | None = None,
        http_client: object | None = None,
        storage: object | None = None,
        url_crawler: object | None = None,
        allow_crawl4ai_cold_start: bool = True,
    ):
        del settings, http_client, storage
        assert material_arg is material
        if url_crawler is not crawler:
            raise AssertionError("worker crawler 未透传到 parse_material")
        assert allow_crawl4ai_cold_start is False
        raise ParseError(error_code="TEST_STOP", message="stop after parse")

    monkeypatch.setattr(ingestion_batches, "get_settings", _settings)
    monkeypatch.setattr(ingestion_batches, "parse_material", fake_parse_material)

    resources = SimpleNamespace(
        sessionmaker=lambda: session_scope(),
        http_client=object(),
        url_crawler=crawler,
    )
    doc = SimpleNamespace(id=uuid4(), kb_id=kb_id, source_ref=str(material_id))

    with pytest.raises(ingestion_batches._ProcessingFailure) as exc_info:
        await ingestion_batches._process_doc(doc=doc, resources=resources)

    assert exc_info.value.code == "TEST_STOP"

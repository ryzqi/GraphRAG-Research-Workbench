from types import SimpleNamespace

import pytest

from app.api.dependencies import services as service_deps
from app.api.v1.endpoints import health as health_module
from app.core.settings import Settings
from app.models.source_material import SourceType
from app.services.ingestion_batch_service import IngestionBatchService
from app.services.parsing import material_parser


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_build_material_service_uses_app_object_storage(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeService:
        def __init__(
            self,
            db: object,
            *,
            http_client: object | None = None,
            object_storage: object | None = None,
        ) -> None:
            captured["db"] = db
            captured["http_client"] = http_client
            captured["object_storage"] = object_storage

    monkeypatch.setattr(service_deps, "MaterialService", _FakeService)

    db = object()
    resources = SimpleNamespace(http_client=object(), object_storage=object())
    service_deps.build_material_service(db=db, resources=resources)

    assert captured["db"] is db
    assert captured["http_client"] is resources.http_client
    assert captured["object_storage"] is resources.object_storage


def test_build_kb_bootstrap_job_service_uses_app_object_storage(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeService:
        def __init__(
            self,
            db: object,
            *,
            http_client: object | None = None,
            object_storage: object | None = None,
        ) -> None:
            captured["db"] = db
            captured["http_client"] = http_client
            captured["object_storage"] = object_storage

    monkeypatch.setattr(service_deps, "KBBootstrapJobService", _FakeService)

    db = object()
    resources = SimpleNamespace(http_client=object(), object_storage=object())
    service_deps.build_kb_bootstrap_job_service(db=db, resources=resources)

    assert captured["db"] is db
    assert captured["http_client"] is resources.http_client
    assert captured["object_storage"] is resources.object_storage


def test_build_knowledge_base_service_uses_app_object_storage(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeService:
        def __init__(
            self,
            db: object,
            *,
            object_storage: object | None = None,
        ) -> None:
            captured["db"] = db
            captured["object_storage"] = object_storage

    monkeypatch.setattr(service_deps, "KnowledgeBaseService", _FakeService)

    db = object()
    resources = SimpleNamespace(object_storage=object())
    service_deps.build_knowledge_base_service(db=db, resources=resources)

    assert captured["db"] is db
    assert captured["object_storage"] is resources.object_storage


def test_ingestion_batch_service_accepts_shared_object_storage() -> None:
    storage = object()

    service = IngestionBatchService(object(), object_storage=storage)

    assert service._storage is storage


async def test_check_minio_uses_shared_object_storage() -> None:
    calls: list[str] = []
    storage = SimpleNamespace(
        _client=SimpleNamespace(bucket_exists=lambda bucket: calls.append(bucket)),
        _settings=SimpleNamespace(minio_bucket_uploads="uploads"),
    )

    await health_module._check_minio(storage)

    assert calls == ["uploads"]


async def test_parse_material_upload_requires_shared_object_storage(
    monkeypatch,
) -> None:
    class _UnexpectedObjectStorage:
        def __init__(self) -> None:
            raise AssertionError("unexpected ObjectStorage() construction")

    monkeypatch.setattr(material_parser, "ObjectStorage", _UnexpectedObjectStorage)

    material = SimpleNamespace(
        source_type=SourceType.UPLOAD,
        uri="minio://uploads/example.txt",
        mime_type="text/plain",
    )

    with pytest.raises(RuntimeError, match="storage"):
        await material_parser.parse_material(material, settings=_make_settings())

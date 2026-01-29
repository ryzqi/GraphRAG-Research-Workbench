import io
import uuid
from types import SimpleNamespace

import pytest
from fastapi import Response
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.models.source_material import SourceType
from app.schemas.knowledge_bases import IndexConfig, KnowledgeBaseIndexConfigUpdateRequest


@pytest.mark.asyncio
async def test_upload_material_rejects_non_md_when_markdown_heading_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.endpoints import materials as materials_ep

    kb_id = uuid.uuid4()
    kb = SimpleNamespace(
        id=kb_id,
        index_config=IndexConfig.model_validate(
            {"chunking": {"general_strategy": "markdown_heading"}}
        ).model_dump(mode="json"),
    )

    class _KbService:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _kb_id: uuid.UUID) -> object | None:
            return kb

    monkeypatch.setattr(materials_ep, "KnowledgeBaseService", _KbService)

    file = UploadFile(filename="x.pdf", file=io.BytesIO(b"noop"))
    with pytest.raises(HTTPException) as exc:
        await materials_ep.upload_material(
            db=object(),
            kb_id=kb_id,
            title="t",
            file=file,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "KB_MARKDOWN_ONLY"


@pytest.mark.asyncio
async def test_update_index_config_rejects_switch_to_markdown_heading_if_non_md_materials_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.endpoints import knowledge_bases as kb_ep

    kb_id = uuid.uuid4()
    kb = SimpleNamespace(
        id=kb_id,
        name="kb",
        description=None,
        tags=None,
        status="active",
        index_config=IndexConfig().model_dump(mode="json"),
        created_at=None,
        updated_at=None,
    )

    class _KbService:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _kb_id: uuid.UUID) -> object | None:
            return kb

    class _MaterialService:
        def __init__(self, _db: object) -> None:
            pass

        async def list_by_kb(
            self, _kb_id: uuid.UUID, *, skip: int = 0, limit: int = 100
        ) -> list[object]:
            if skip > 0:
                return []
            return [
                SimpleNamespace(
                    source_type=SourceType.UPLOAD,
                    uri="minio://bucket/kb/material/x.pdf",
                )
            ]

    monkeypatch.setattr(kb_ep, "KnowledgeBaseService", _KbService)
    monkeypatch.setattr(kb_ep, "MaterialService", _MaterialService)

    body = KnowledgeBaseIndexConfigUpdateRequest(
        index_config=IndexConfig.model_validate(
            {"chunking": {"general_strategy": "markdown_heading"}}
        )
    )
    with pytest.raises(HTTPException) as exc:
        await kb_ep.update_index_config(
            db=object(),
            kb_id=kb_id,
            body=body,
            response=Response(),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "KB_MARKDOWN_ONLY_CONFLICT"


from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.knowledge_base_service import KnowledgeBaseService


def _make_kb(
    *,
    kb_id: uuid.UUID | None = None,
    name: str = "上下文增强测试",
    description: str | None = "原始描述",
    tags: list[str] | None = None,
):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=kb_id or uuid.uuid4(),
        name=name,
        description=description,
        tags=tags if tags is not None else ["原标签"],
        status="active",
        readiness="ready",
        readiness_updated_at=now,
        current_config_version=1,
        index_config={},
        created_at=now,
        updated_at=now,
    )


class _FakeSession:
    def __init__(self, *, kb) -> None:
        self.kb = kb
        self.commit_calls = 0
        self.refresh_calls: list[object] = []

    async def get(self, _model, key):
        return self.kb if key == self.kb.id else None

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(self, value) -> None:
        self.refresh_calls.append(value)


@pytest.mark.asyncio
async def test_service_update_does_not_clear_optional_fields_when_field_not_explicitly_submitted() -> None:
    kb = _make_kb(description="保留描述", tags=["保留标签"])
    session = _FakeSession(kb=kb)
    service = KnowledgeBaseService(session)

    updated = await service.update(
        kb_id=kb.id,
        name="新的名称",
        description=None,
        tags=None,
        fields_to_update={"name"},
    )

    assert updated is kb
    assert kb.name == "新的名称"
    assert kb.description == "保留描述"
    assert kb.tags == ["保留标签"]
    assert session.commit_calls == 1
    assert session.refresh_calls == [kb]


@pytest.mark.asyncio
async def test_service_update_clears_optional_fields_when_null_is_explicitly_submitted() -> None:
    kb = _make_kb(description="待删除描述", tags=["待删除标签"])
    session = _FakeSession(kb=kb)
    service = KnowledgeBaseService(session)

    updated = await service.update(
        kb_id=kb.id,
        description=None,
        tags=None,
        fields_to_update={"description", "tags"},
    )

    assert updated is kb
    assert kb.description is None
    assert kb.tags is None
    assert session.commit_calls == 1
    assert session.refresh_calls == [kb]


def test_update_endpoint_source_tracks_explicit_submitted_fields() -> None:
    endpoint_path = Path(__file__).resolve().parents[1] / "src/app/api/v1/endpoints/knowledge_bases.py"
    source = endpoint_path.read_text(encoding="utf-8")

    assert "model_fields_set" in source
    assert "fields_to_update=" in source

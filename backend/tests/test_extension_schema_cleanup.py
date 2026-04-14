from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tool_extension import ExtensionStatus, ExtensionTransport, ToolExtension
from app.repositories.extension_repository import ExtensionRepository
from app.schemas.extensions import (
    ToolExtensionCreate,
    ToolExtensionRead,
    ToolExtensionUpdate,
)
from app.services.extension_service import ExtensionService


class _InMemoryExtensionRepository:
    def __init__(self) -> None:
        self.extension: ToolExtension | None = None

    async def get_by_id(self, extension_id: uuid.UUID) -> ToolExtension | None:
        if self.extension is None or self.extension.id != extension_id:
            return None
        return self.extension

    def add(self, extension: ToolExtension) -> None:
        now = datetime.now(UTC)
        extension.id = uuid.uuid4()
        extension.created_at = now
        extension.updated_at = now
        self.extension = extension

    async def refresh(self, extension: ToolExtension) -> None:
        extension.updated_at = datetime.now(UTC)


def _http_create_payload() -> dict[str, object]:
    return {
        "name": "sample-extension",
        "transport": "http",
        "status": "enabled",
        "http_config": {
            "url": "https://example.com/mcp",
            "protocol": "streamable_http",
            "headers": {},
            "auth": {"type": "none", "token": None},
        },
    }


@pytest.mark.parametrize(
    ("schema_cls", "payload"),
    [
        (
            ToolExtensionCreate,
            {
                **_http_create_payload(),
                "observability_config": {
                    "emit_metrics": True,
                    "log_level_override": "debug",
                },
            },
        ),
        (
            ToolExtensionUpdate,
            {
                "observability_config": {
                    "emit_metrics": False,
                    "log_level_override": "INFO",
                }
            },
        ),
    ],
)
def test_extension_write_schemas_reject_legacy_observability_config(
    schema_cls: type[ToolExtensionCreate | ToolExtensionUpdate],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        schema_cls.model_validate(payload)

    errors = exc_info.value.errors()
    assert errors[0]["type"] == "extra_forbidden"
    assert errors[0]["loc"] == ("observability_config",)


def test_tool_extension_read_omits_legacy_observability_config() -> None:
    now = datetime.now(UTC)
    extension = ToolExtension(
        id=uuid.uuid4(),
        name="sample-extension",
        transport=ExtensionTransport.HTTP,
        status=ExtensionStatus.ENABLED,
        http_config={
            "url": "https://example.com/mcp",
            "protocol": "streamable_http",
            "headers": {},
            "auth": {"type": "none", "token": None},
        },
        stdio_config=None,
        created_at=now,
        updated_at=now,
    )
    setattr(
        extension,
        "observability_config",
        {
        "emit_metrics": True,
        "log_level_override": "DEBUG",
        },
    )

    payload = ToolExtensionRead.model_validate(extension).model_dump(mode="json")

    assert "observability_config" not in payload


@pytest.mark.asyncio
async def test_extension_service_create_and_update_return_schema_without_observability_field() -> None:
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    repository = _InMemoryExtensionRepository()
    service = ExtensionService(
        cast(AsyncSession, db),
        repository=cast(ExtensionRepository, repository),
    )

    created = await service.create_extension(
        ToolExtensionCreate.model_validate(_http_create_payload())
    )
    created_payload = created.model_dump(mode="json")

    assert "observability_config" not in created_payload
    assert created_payload["http_config"]["url"] == "https://example.com/mcp"

    updated = await service.update_extension(
        created.id,
        ToolExtensionUpdate.model_validate({"status": "disabled"}),
    )

    assert updated is not None
    updated_payload = updated.model_dump(mode="json")
    assert updated_payload["status"] == "disabled"
    assert "observability_config" not in updated_payload

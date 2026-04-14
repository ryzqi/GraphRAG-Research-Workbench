from __future__ import annotations

import uuid

import pytest

from app.core.errors import AppError
from app.services.material_service import MaterialService


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commit_called = False
        self.refresh_called = False

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.commit_called = True

    async def refresh(self, _instance: object) -> None:
        self.refresh_called = True


@pytest.mark.asyncio
async def test_material_service_create_url_rejects_unsafe_url() -> None:
    session = _FakeSession()
    service = MaterialService(session)  # type: ignore[arg-type]

    with pytest.raises(AppError) as exc_info:
        await service.create_url(
            kb_id=uuid.uuid4(),
            title="本地地址",
            url="http://127.0.0.1/private",
        )

    assert exc_info.value.code == "URL_SSRF_BLOCKED"
    assert session.added == []
    assert session.commit_called is False
    assert session.refresh_called is False

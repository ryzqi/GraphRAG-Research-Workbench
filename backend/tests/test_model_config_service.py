from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import MissingGreenlet

from app.models.model_config import ModelProvider
from app.services.model_config_service import ModelConfigService


class _SelectionWithLazyUpdatedAt:
    def __init__(self) -> None:
        self.active_provider = ModelProvider.OPENAI
        self.active_model = "gpt-4o-mini"
        self._updated_at = datetime.now(timezone.utc)
        self._is_refreshed = False

    @property
    def updated_at(self) -> datetime:
        if not self._is_refreshed:
            raise MissingGreenlet("greenlet_spawn has not been called")
        return self._updated_at

    def mark_refreshed(self) -> None:
        self._is_refreshed = True


def _settings_stub() -> SimpleNamespace:
    return SimpleNamespace(
        app_env="test",
        model_config_kms_key="test-kms-key",
    )


def _provider_row_stub() -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        provider=ModelProvider.OPENAI,
        enabled=True,
        base_url="https://api.openai.com/v1",
        models=["gpt-4o-mini"],
        thinking_enabled=True,
        thinking_level="high",
        api_key_encrypted=None,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_get_config_refreshes_selection_before_reading_updated_at() -> None:
    selection = _SelectionWithLazyUpdatedAt()
    db = MagicMock()
    db.get = AsyncMock(return_value=selection)

    async def _refresh(obj: _SelectionWithLazyUpdatedAt) -> None:
        assert obj is selection
        obj.mark_refreshed()

    db.refresh = AsyncMock(side_effect=_refresh)

    service = ModelConfigService(db=db, settings=_settings_stub())
    service._ensure_defaults = AsyncMock()
    service._list_provider_rows = AsyncMock(return_value=[_provider_row_stub()])

    config = await service.get_config()

    assert config.active_provider.value == ModelProvider.OPENAI.value
    assert config.updated_at == selection.updated_at
    db.refresh.assert_awaited_once_with(selection)

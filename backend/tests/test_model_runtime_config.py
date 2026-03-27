from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.settings import get_settings
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.models.model_config import ModelProvider


class _FakeScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeExecuteResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._rows)


class _FakeSelection:
    def __init__(self) -> None:
        self.active_provider = ModelProvider.OLLAMA
        self.active_model = 'kimi-k2.5:cloud'
        self._updated_at = datetime(2026, 3, 27, tzinfo=timezone.utc)
        self._refreshed = False

    @property
    def updated_at(self) -> datetime:
        if not self._refreshed:
            raise AssertionError('updated_at accessed before refresh')
        return self._updated_at


class _FakeSession:
    def __init__(self, rows: list[object], selection: _FakeSelection) -> None:
        self._rows = rows
        self._selection = selection
        self.refresh_calls: list[tuple[object, tuple[str, ...] | None]] = []

    async def execute(self, _statement: object) -> _FakeExecuteResult:
        return _FakeExecuteResult(self._rows)

    async def get(self, _model: object, _pk: object) -> _FakeSelection:
        return self._selection

    async def refresh(self, obj: object, attribute_names: list[str] | None = None) -> None:
        assert obj is self._selection
        self.refresh_calls.append((obj, tuple(attribute_names) if attribute_names else None))
        self._selection._refreshed = True


@pytest.mark.asyncio
async def test_load_snapshot_refreshes_selection_before_reading_updated_at() -> None:
    provider_row = SimpleNamespace(
        provider=ModelProvider.OLLAMA,
        enabled=True,
        base_url='http://127.0.0.1:11434',
        api_key_encrypted=None,
        models=['kimi-k2.5:cloud'],
        thinking_enabled=True,
        thinking_level='high',
    )
    selection = _FakeSelection()
    session = _FakeSession(rows=[provider_row], selection=selection)

    snapshot = await ModelRuntimeConfigManager._load_snapshot(
        db=session,
        settings=get_settings(),
    )

    assert session.refresh_calls == [(
        selection,
        ('active_provider', 'active_model', 'updated_at'),
    )]
    assert snapshot.active_provider == ModelProvider.OLLAMA
    assert snapshot.active_model == 'kimi-k2.5:cloud'
    assert snapshot.updated_at == datetime(2026, 3, 27, tzinfo=timezone.utc)

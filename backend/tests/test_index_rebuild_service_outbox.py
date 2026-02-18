from __future__ import annotations

import sys
import types
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.index_rebuild_job import IndexRebuildJob
from app.models.index_rebuild_task_outbox import IndexRebuildTaskOutbox
from app.services.index_rebuild_service import IndexRebuildService


class _FakeScalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _FakeResult:
    def __init__(self, *, scalar: object | None = None, scalars: list[object] | None = None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one(self) -> object:
        return self._scalar

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._scalars)


@pytest.mark.asyncio
async def test_create_job_writes_rebuild_outbox_and_triggers_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    db = AsyncMock()
    running_job = SimpleNamespace(status="running", finished_at=None)
    active_snapshot = SimpleNamespace(is_active=True)
    db.execute = AsyncMock(
        side_effect=[
            _FakeResult(scalars=[running_job]),
            _FakeResult(scalar=2),
            _FakeResult(scalars=[active_snapshot]),
        ]
    )
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    delay_mock = MagicMock()
    fake_dispatch_module = types.SimpleNamespace(
        dispatch_index_rebuild_outbox=SimpleNamespace(delay=delay_mock)
    )
    monkeypatch.setitem(
        sys.modules,
        "app.worker.tasks.index_rebuild_outbox_dispatcher",
        fake_dispatch_module,
    )

    kb = SimpleNamespace(
        id=uuid.uuid4(),
        index_config={"chunking": {"general_strategy": "token"}},
        current_config_version=1,
    )

    service = IndexRebuildService(db)
    await service.create_job(kb=kb, index_config={"chunking": {"general_strategy": "token"}})

    added_objects = [call.args[0] for call in db.add.call_args_list]
    assert any(isinstance(obj, IndexRebuildJob) for obj in added_objects)
    assert any(isinstance(obj, IndexRebuildTaskOutbox) for obj in added_objects)
    assert delay_mock.call_count == 1

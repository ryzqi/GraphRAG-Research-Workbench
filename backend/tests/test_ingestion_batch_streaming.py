from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
import uuid

import pytest

from app.models.ingestion_batch import IngestionDocStatus
from app.services import ingestion_batch_change_bus as change_bus_module
from app.services import ingestion_batch_service as ingestion_service_module
from app.services import streaming as streaming_module


class _FakeChangeBus:
    def __init__(self) -> None:
        self.publish_calls: list[tuple[uuid.UUID, str]] = []

    async def publish(self, *, batch_id: uuid.UUID, event: str) -> None:
        self.publish_calls.append((batch_id, event))


class _FakeDbSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


@pytest.mark.asyncio
async def test_stream_snapshots_uses_change_listener_for_realtime_updates() -> None:
    states = iter([{"status": "queued"}, {"status": "processing"}])
    fetch_calls = 0

    async def fetcher() -> dict[str, str]:
        nonlocal fetch_calls
        fetch_calls += 1
        return next(states)

    class _Listener:
        def __init__(self) -> None:
            self.wait_calls: list[float] = []

        async def wait(self, *, timeout: float) -> bool:
            self.wait_calls.append(timeout)
            return True

    listener = _Listener()

    stream = streaming_module.stream_snapshots(
        fetcher=fetcher,
        serializer=lambda item: item,
        is_terminal=lambda _item: False,
        poll_interval=10.0,
        heartbeat_interval=10.0,
        heartbeat_factory=lambda: {"kind": "heartbeat"},
        change_listener=listener,
        initial_event="snapshot",
    )

    first = await anext(stream)
    second = await anext(stream)
    await stream.aclose()

    assert first == ("snapshot", {"status": "queued"})
    assert second == ("update", {"status": "processing"})
    assert fetch_calls == 2
    assert listener.wait_calls == [10.0]


@pytest.mark.asyncio
async def test_stream_snapshots_falls_back_to_polling_when_listener_wait_fails() -> None:
    states = iter([{"status": "queued"}, {"status": "processing"}])

    async def fetcher() -> dict[str, str]:
        return next(states)

    class _BrokenListener:
        async def wait(self, *, timeout: float) -> bool:
            raise RuntimeError(f"listener failed at timeout={timeout}")

    stream = streaming_module.stream_snapshots(
        fetcher=fetcher,
        serializer=lambda item: item,
        is_terminal=lambda _item: False,
        poll_interval=0.0,
        heartbeat_interval=10.0,
        heartbeat_factory=lambda: {"kind": "heartbeat"},
        change_listener=_BrokenListener(),
        initial_event="snapshot",
    )

    first = await anext(stream)
    second = await anext(stream)
    await stream.aclose()

    assert first == ("snapshot", {"status": "queued"})
    assert second == ("update", {"status": "processing"})


@pytest.mark.asyncio
async def test_change_bus_listen_closes_pubsub_when_subscribe_fails() -> None:
    state = {"closed": False}

    class _BrokenPubSub:
        async def subscribe(self, _channel: str) -> None:
            raise RuntimeError("subscribe failed")

        async def aclose(self) -> None:
            state["closed"] = True

    bus = change_bus_module.IngestionBatchChangeBus(
        redis=SimpleNamespace(pubsub=lambda: _BrokenPubSub())
    )

    with pytest.raises(RuntimeError, match="subscribe failed"):
        async with bus.listen(batch_id=uuid.uuid4()):
            pytest.fail("listen should not yield when subscribe fails")

    assert state["closed"] is True


@pytest.mark.asyncio
async def test_open_ingestion_batch_change_bus_falls_back_to_none(monkeypatch) -> None:
    close_calls: list[object] = []

    def _broken_create_redis_client(_settings: object) -> object:
        raise RuntimeError("redis unavailable")

    async def _fake_close_redis_client(redis: object | None) -> None:
        close_calls.append(redis)

    monkeypatch.setattr(
        change_bus_module,
        "create_redis_client",
        _broken_create_redis_client,
    )
    monkeypatch.setattr(
        change_bus_module,
        "close_redis_client",
        _fake_close_redis_client,
    )

    async with change_bus_module.open_ingestion_batch_change_bus(
        settings=object(),
    ) as change_bus:
        assert change_bus is None

    assert close_calls == [None]


@pytest.mark.asyncio
async def test_ingestion_batch_service_commit_publishes_pending_batch_changes(
    monkeypatch,
) -> None:
    batch_id = uuid.uuid4()
    db = _FakeDbSession()
    change_bus = _FakeChangeBus()
    service = ingestion_service_module.IngestionBatchService(
        db,
        object_storage=object(),
        change_bus=change_bus,
    )

    async def _append_event(**_kwargs: object) -> None:
        return None

    service._append_event = _append_event
    doc = SimpleNamespace(
        id=uuid.uuid4(),
        batch_id=batch_id,
        status=IngestionDocStatus.QUEUED,
    )

    await service._set_doc_status(
        doc,
        IngestionDocStatus.PROCESSING,
        reason="doc_start",
    )
    await service.commit()

    assert db.commit_calls == 1
    assert change_bus.publish_calls == [(batch_id, "changed")]


@pytest.mark.asyncio
async def test_stream_batch_updates_passes_change_listener_to_stream_snapshots(
    monkeypatch,
) -> None:
    batch_id = uuid.uuid4()
    captured: dict[str, object] = {}

    class _FakeListener:
        async def wait(self, *, timeout: float) -> bool:
            return False

    @asynccontextmanager
    async def _listen(*, batch_id: uuid.UUID):
        captured["listen_batch_id"] = batch_id
        yield _FakeListener()

    async def _fake_stream_snapshots(**kwargs):
        captured.update(kwargs)
        yield "snapshot", {"batch_id": str(batch_id)}

    service = ingestion_service_module.IngestionBatchService(
        object(),
        object_storage=object(),
        change_bus=SimpleNamespace(listen=_listen),
    )
    monkeypatch.setattr(
        ingestion_service_module,
        "stream_snapshots",
        _fake_stream_snapshots,
    )

    results = []
    async for item in service.stream_batch_updates(batch_id=batch_id):
        results.append(item)

    assert results == [("snapshot", {"batch_id": str(batch_id)})]
    assert captured["listen_batch_id"] == batch_id
    assert captured["change_listener"] is not None
    assert captured["initial_event"] == "snapshot"

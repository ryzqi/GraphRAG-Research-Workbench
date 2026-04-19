import asyncio

import pytest

from app.api import sse as sse_module


@pytest.mark.asyncio
async def test_encode_sse_emits_error_event_when_producer_fails() -> None:
    async def producer():
        yield "greeting", {"hello": "world"}
        raise RuntimeError("boom")

    collected: list[str] = []
    async for chunk in sse_module.encode_sse(producer()):
        collected.append(chunk)

    combined = "".join(collected)
    assert "event: greeting" in combined
    assert "event: error" in combined
    assert "STREAM_PRODUCER_ERROR" in combined
    assert "boom" in combined


@pytest.mark.asyncio
async def test_encode_sse_applies_backpressure_with_bounded_queue(
    monkeypatch,
) -> None:
    peak_qsize = 0

    class TrackingQueue(asyncio.Queue):
        async def put(self, item) -> None:
            nonlocal peak_qsize
            await super().put(item)
            peak_qsize = max(peak_qsize, self.qsize())

    async def producer():
        for index in range(20):
            yield "tick", {"index": index}

    monkeypatch.setattr(sse_module.asyncio, "Queue", TrackingQueue)

    collected: list[str] = []
    async for chunk in sse_module.encode_sse(producer(), queue_maxsize=2):
        collected.append(chunk)
        await asyncio.sleep(0.01)

    assert len(collected) == 20
    assert peak_qsize <= 2

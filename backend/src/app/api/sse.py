from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterable, AsyncIterator, Callable

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@dataclass
class SseHeartbeatStats:
    """Collect heartbeat emission stats for downstream observability."""

    sent_count: int = 0
    gap_ms_samples: list[int] = field(default_factory=list)
    _last_sent_monotonic: float | None = None

    def record(self, *, now_monotonic: float | None = None) -> None:
        now_value = (
            float(now_monotonic)
            if isinstance(now_monotonic, (int, float))
            else time.perf_counter()
        )
        if self._last_sent_monotonic is not None:
            gap_ms = max(0, int(round((now_value - self._last_sent_monotonic) * 1000.0)))
            self.gap_ms_samples.append(gap_ms)
        self._last_sent_monotonic = now_value
        self.sent_count += 1


def _json_dumps(data: Any) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def format_sse(event: str, data: Any) -> str:
    """将事件编码为 SSE 文本。"""
    payload = _json_dumps(data)
    lines = payload.splitlines() or [""]
    return "event: {event}\n".format(event=event) + "".join(
        "data: {line}\n".format(line=line) for line in lines
    ) + "\n"


def format_sse_comment(comment: str) -> str:
    """生成 SSE 注释（心跳）。"""
    return ": {comment}\n\n".format(comment=comment)


async def encode_sse(
    events: AsyncIterable[tuple[str, Any]],
    *,
    heartbeat_interval: float | None = None,
    heartbeat_factory: Callable[[], Any] | None = None,
    heartbeat_stats: SseHeartbeatStats | None = None,
) -> AsyncIterator[str]:
    """将事件序列转换为 SSE 字符串流。"""
    heartbeat_enabled = (
        heartbeat_interval is not None and heartbeat_interval > 0
    )
    queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()

    async def _drain_events() -> None:
        try:
            async for event, data in events:
                await queue.put((event, data))
        finally:
            await queue.put(None)

    producer = asyncio.create_task(_drain_events())
    try:
        while True:
            try:
                item = (
                    await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                    if heartbeat_enabled
                    else await queue.get()
                )
            except asyncio.TimeoutError:
                if isinstance(heartbeat_stats, SseHeartbeatStats):
                    heartbeat_stats.record()
                if callable(heartbeat_factory):
                    yield format_sse("heartbeat", heartbeat_factory())
                else:
                    yield format_sse_comment("heartbeat")
                continue

            if item is None:
                break
            event, data = item
            yield format_sse(event, data)
    finally:
        if not producer.done():
            producer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer

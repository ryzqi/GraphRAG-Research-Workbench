from __future__ import annotations

import asyncio

import pytest

from app.api.sse import encode_sse


@pytest.mark.asyncio
async def test_encode_sse_keeps_source_generator_on_single_task() -> None:
    observed_tasks: list[asyncio.Task[object] | None] = []

    async def source():
        observed_tasks.append(asyncio.current_task())
        yield ("meta", {"step": 1})
        observed_tasks.append(asyncio.current_task())
        yield ("final", {"step": 2})

    encoded = encode_sse(source(), heartbeat_interval=None)
    chunks: list[str] = []
    async for chunk in encoded:
        chunks.append(chunk)

    assert len(chunks) == 2
    assert observed_tasks
    assert all(task is observed_tasks[0] for task in observed_tasks)

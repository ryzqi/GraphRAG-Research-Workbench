from __future__ import annotations

import pytest

from app.api.sse import format_sse
from app.services.streaming import (
    StreamState,
    apply_updates_chunk,
    extract_message_text,
    stream_snapshots,
)


class FakeChunk:
    def __init__(self, *, content=None, text=None):
        self.content = content
        self.text = text


def test_format_sse_encodes_event() -> None:
    encoded = format_sse("delta", {"text": "hi"})
    assert encoded.startswith("event: delta\n")
    assert "data: {\"text\":\"hi\"}" in encoded
    assert encoded.endswith("\n\n")

def test_extract_message_text_handles_content() -> None:
    assert extract_message_text(FakeChunk(content="hello")) == "hello"
    assert extract_message_text(FakeChunk(text="hi")) == "hi"
    assert (
        extract_message_text(
            FakeChunk(content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
        )
        == "ab"
    )


def test_apply_updates_chunk_merges_and_interrupts() -> None:
    state = StreamState()
    interrupts = apply_updates_chunk(
        state,
        {"model": {"messages": ["m1"], "stage_summaries": {"s": 1}, "metrics": {"m": 1}}},
    )
    assert interrupts == []
    assert state.messages == ["m1"]

    interrupts = apply_updates_chunk(state, {"__interrupt__": ["x"]})
    assert interrupts == ["x"]


class FakeRun:
    def __init__(self, status: str) -> None:
        self.status = status


@pytest.mark.asyncio
async def test_stream_snapshots_update_final() -> None:
    runs = [FakeRun("running"), FakeRun("succeeded")]

    async def _fetch():
        return runs.pop(0) if runs else FakeRun("succeeded")

    def _serialize(run: FakeRun) -> dict:
        return {"status": run.status}

    def _is_terminal(run: FakeRun) -> bool:
        return run.status == "succeeded"

    events: list[tuple[str, dict]] = []
    async for event, data in stream_snapshots(
        _fetch,
        _serialize,
        _is_terminal,
        poll_interval=0,
    ):
        events.append((event, data))
        if event == "final":
            break

    assert events[0][0] == "update"
    assert events[-1][0] == "final"

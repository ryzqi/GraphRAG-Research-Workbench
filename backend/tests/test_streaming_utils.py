from __future__ import annotations

import pytest

from app.api.sse import format_sse
from app.services.streaming import (
    DeltaKind,
    LegacyThinkParser,
    StreamDelta,
    StreamState,
    apply_updates_chunk,
    build_think_delta,
    extract_answer_text,
    extract_stream_delta,
    strip_legacy_think_tags,
    stream_snapshots,
)


class FakeChunk:
    def __init__(
        self,
        *,
        content=None,
        text=None,
        msg_type=None,
        tool_call_chunks=None,
        tool_calls=None,
        additional_kwargs=None,
    ):
        self.content = content
        self.text = text
        if msg_type is not None:
            self.type = msg_type
        if tool_call_chunks is not None:
            self.tool_call_chunks = tool_call_chunks
        if tool_calls is not None:
            self.tool_calls = tool_calls
        if additional_kwargs is not None:
            self.additional_kwargs = additional_kwargs


def test_format_sse_encodes_event() -> None:
    encoded = format_sse("delta", {"text": "hi"})
    assert encoded.startswith("event: delta\n")
    assert "data: {\"text\":\"hi\"}" in encoded
    assert encoded.endswith("\n\n")


def test_extract_stream_delta_returns_answer() -> None:
    """测试普通文本内容返回 answer delta。"""
    deltas = extract_stream_delta(FakeChunk(content="hello"))
    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.kind == DeltaKind.ANSWER
    assert delta.content == "hello"


def test_extract_stream_delta_returns_thinking_in_tools_node() -> None:
    """测试在 tools 节点上下文中返回 thinking delta。"""
    deltas = extract_stream_delta(
        FakeChunk(content="step"), {"langgraph_node": "tools"}
    )
    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.kind == DeltaKind.THINKING
    assert delta.content == "step"


def test_extract_stream_delta_handles_thinking_content_block() -> None:
    """测试 thinking 类型内容块返回 thinking delta。"""
    deltas = extract_stream_delta(
        FakeChunk(content=[{"type": "thinking", "text": "reasoning..."}])
    )
    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.kind == DeltaKind.THINKING
    assert delta.content == "reasoning..."


def test_extract_stream_delta_handles_text_content_block() -> None:
    """测试 text 类型内容块返回 answer delta。"""
    deltas = extract_stream_delta(
        FakeChunk(content=[{"type": "text", "text": "answer"}])
    )
    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.kind == DeltaKind.ANSWER
    assert delta.content == "answer"


def test_extract_stream_delta_skips_tool_messages() -> None:
    """测试跳过 ToolMessage 类型。"""
    deltas = extract_stream_delta(FakeChunk(content="tool out", msg_type="tool"))
    assert deltas == []


def test_extract_stream_delta_handles_tool_call_chunks() -> None:
    """测试 tool_call_chunks 返回 tool_call delta。"""
    deltas = extract_stream_delta(
        FakeChunk(tool_call_chunks=[{"name": "foo", "args": {}, "id": "call1"}])
    )
    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.kind == DeltaKind.TOOL_CALL
    assert delta.tool_name == "foo"


def test_extract_stream_delta_handles_tool_calls() -> None:
    """测试完整 tool_calls 返回 tool_call delta。"""
    deltas = extract_stream_delta(
        FakeChunk(content="", tool_calls=[{"name": "bar", "args": {"x": 1}, "id": "call2"}])
    )
    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.kind == DeltaKind.TOOL_CALL
    assert delta.tool_name == "bar"


def test_extract_stream_delta_with_tool_calls_and_content() -> None:
    """测试有内容的 tool_calls 返回 tool_call delta（优先工具调用）。"""
    deltas = extract_stream_delta(
        FakeChunk(content="ok", tool_calls=[{"name": "foo", "args": {}}])
    )
    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.kind == DeltaKind.TOOL_CALL


def test_legacy_think_parser_splits_across_chunks() -> None:
    parser = LegacyThinkParser()
    chunks = ["<th", "ink>思考", "</thi", "nk>答案"]
    deltas: list[StreamDelta] = []
    for chunk in chunks:
        deltas.extend(parser.feed(chunk))
    deltas.extend(parser.flush())

    think = "".join(delta.content for delta in deltas if delta.kind == DeltaKind.THINKING)
    answer = "".join(delta.content for delta in deltas if delta.kind == DeltaKind.ANSWER)
    assert think == "思考"
    assert answer == "答案"


def test_strip_legacy_think_tags_handles_unclosed() -> None:
    text = "<think>未闭合"
    assert strip_legacy_think_tags(text) == "未闭合"


def test_extract_answer_text_skips_thinking_blocks() -> None:
    content = [
        {"type": "thinking", "text": "推理"},
        {"type": "text", "text": "答案"},
    ]
    assert extract_answer_text(content) == "答案"


def test_stream_delta_to_dict() -> None:
    """测试 StreamDelta.to_dict 序列化。"""
    delta = StreamDelta(
        kind=DeltaKind.ANSWER,
        content="hello world",
    )
    d = delta.to_dict()
    assert d["kind"] == "answer"
    assert d["content"] == "hello world"
    assert "tool_name" not in d


def test_stream_delta_tool_call_to_dict() -> None:
    """测试工具调用 delta 序列化。"""
    delta = StreamDelta(
        kind=DeltaKind.TOOL_CALL,
        tool_call_id="call123",
        tool_name="get_weather",
        tool_args={"location": "Beijing"},
    )
    d = delta.to_dict()
    assert d["kind"] == "tool_call"
    assert d["tool_name"] == "get_weather"
    assert d["tool_call_id"] == "call123"
    assert d["tool_args"] == {"location": "Beijing"}


def test_build_think_delta_from_messages() -> None:
    from langchain.messages import AIMessage, ToolMessage

    ai = AIMessage(
        content="",
        tool_calls=[{"name": "GetWeather", "args": {"location": "SF"}, "id": "call1", "type": "tool_call"}],
    )
    tool_msg = ToolMessage(content="sunny", tool_call_id="call1", name="GetWeather")
    delta = build_think_delta([ai, tool_msg])
    assert delta is not None
    assert delta.kind == DeltaKind.THINKING
    assert "工具调用" in delta.content
    assert "GetWeather" in delta.content
    assert "sunny" in delta.content


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

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Awaitable, Callable


_NON_ANSWER_STREAM_NODES = {
    # KB preprocess / retrieval / reflection nodes
    "merge_context",
    "coref_rewrite",
    "ambiguity_check",
    "normalize_rewrite",
    "decomposition",
    "generate_variants",
    "entity_expand",
    "hyde",
    "prepare_messages",
    "multi_query_check",
    "hyde_check",
    "retrieve",
    "doc_grader",
    "transform_query",
    "answer_review",
}


class DeltaKind(str, Enum):
    """流式增量类型枚举，对齐 LangChain 消息内容块格式。"""

    THINKING = "thinking"  # 推理/思考内容
    ANSWER = "answer"  # 最终回答文本
    TOOL_CALL = "tool_call"  # 工具调用请求
    TOOL_RESULT = "tool_result"  # 工具执行结果
    ATTACHMENT = "attachment"  # 多媒体附件（占位）


@dataclass
class StreamDelta:
    """类型化流式增量结构，用于 SSE delta 事件。

    Attributes:
        kind: 增量类型，区分思考/回答/工具调用/工具结果/附件
        content: 文本内容（thinking/answer 时使用）
        tool_call_id: 工具调用 ID（tool_call/tool_result 时使用）
        tool_name: 工具名称（tool_call/tool_result 时使用）
        tool_args: 工具参数（tool_call 时使用）
        tool_output: 工具输出（tool_result 时使用）
        attachment_type: 附件类型（image/file/audio/video）
        attachment_url: 附件 URL
        attachment_mime: 附件 MIME 类型
    """

    kind: DeltaKind
    content: str = ""
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_output: str | None = None
    attachment_type: str | None = None
    attachment_url: str | None = None
    attachment_mime: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化的字典格式。"""
        result: dict[str, Any] = {"kind": self.kind.value}
        if self.content:
            result["content"] = self.content
        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_name is not None:
            result["tool_name"] = self.tool_name
        if self.tool_args is not None:
            result["tool_args"] = self.tool_args
        if self.tool_output is not None:
            result["tool_output"] = self.tool_output
        if self.attachment_type is not None:
            result["attachment_type"] = self.attachment_type
        if self.attachment_url is not None:
            result["attachment_url"] = self.attachment_url
        if self.attachment_mime is not None:
            result["attachment_mime"] = self.attachment_mime
        return result


class LegacyThinkParser:
    """兼容 legacy <think> 标签的流式解析器（支持跨 chunk）。"""

    _OPEN_TAG = "<think>"
    _CLOSE_TAG = "</think>"

    def __init__(self) -> None:
        self._carry = ""
        self._in_think = False
        self._think_buffer = ""

    def _append_delta(
        self, deltas: list[StreamDelta], kind: DeltaKind, content: str
    ) -> None:
        if content:
            deltas.append(StreamDelta(kind=kind, content=content))

    def _flush_think_buffer(self, deltas: list[StreamDelta]) -> None:
        if self._think_buffer:
            self._append_delta(deltas, DeltaKind.THINKING, self._think_buffer)
            self._think_buffer = ""

    def _split_carry(self, text: str) -> tuple[str, str]:
        max_len = min(len(text), max(len(self._OPEN_TAG), len(self._CLOSE_TAG)) - 1)
        for size in range(max_len, 0, -1):
            suffix = text[-size:]
            if self._OPEN_TAG.startswith(suffix) or self._CLOSE_TAG.startswith(suffix):
                return text[:-size], suffix
        return text, ""

    def feed(self, text: str) -> list[StreamDelta]:
        """解析一段文本，返回拆分后的 delta 列表。"""
        if not text:
            return []

        data = f"{self._carry}{text}"
        self._carry = ""

        deltas: list[StreamDelta] = []
        pos = 0

        while True:
            next_open = data.find(self._OPEN_TAG, pos)
            next_close = data.find(self._CLOSE_TAG, pos)
            next_tag = -1
            is_open = False

            if next_open == -1 and next_close == -1:
                break
            if next_open != -1 and (next_close == -1 or next_open < next_close):
                next_tag = next_open
                is_open = True
            else:
                next_tag = next_close
                is_open = False

            segment = data[pos:next_tag]
            if self._in_think:
                self._think_buffer += segment
            else:
                self._append_delta(deltas, DeltaKind.ANSWER, segment)

            if is_open:
                if self._in_think:
                    # 已处于 think 内，视为普通文本
                    self._think_buffer += self._OPEN_TAG
                else:
                    self._in_think = True
                pos = next_tag + len(self._OPEN_TAG)
            else:
                if self._in_think:
                    self._flush_think_buffer(deltas)
                    self._in_think = False
                # 未进入 think 时遇到关闭标签，直接忽略标签
                pos = next_tag + len(self._CLOSE_TAG)

        tail = data[pos:]
        tail, carry = self._split_carry(tail)
        if carry:
            self._carry = carry
        if tail:
            if self._in_think:
                self._think_buffer += tail
            else:
                self._append_delta(deltas, DeltaKind.ANSWER, tail)

        return deltas

    def flush(self) -> list[StreamDelta]:
        """流式结束时刷新剩余内容。"""
        deltas: list[StreamDelta] = []

        if self._carry:
            if self._in_think:
                self._think_buffer += self._carry
            else:
                self._append_delta(deltas, DeltaKind.ANSWER, self._carry)
            self._carry = ""

        if self._in_think:
            # 未闭合的 think 标签按正文处理
            if self._think_buffer:
                self._append_delta(deltas, DeltaKind.ANSWER, self._think_buffer)
            self._think_buffer = ""
            self._in_think = False
        else:
            self._flush_think_buffer(deltas)

        return deltas


def _should_stream_answer_content(node: str) -> bool:
    """Return whether raw text from a node should be treated as answer content."""
    if not node:
        return True
    if node == "tools":
        return False
    return node not in _NON_ANSWER_STREAM_NODES


def extract_stream_delta(
    token: object,
    meta: dict[str, Any] | None = None,
    legacy_think_parser: LegacyThinkParser | None = None,
) -> list[StreamDelta]:
    """从 LLM token chunk 提取结构化 StreamDelta 列表。

    解析规则（LangChain 1.2.6 标准）：
    - reasoning_content -> thinking delta
    - content (str/list[text]) -> answer delta
    - tool_calls/tool_call_chunks -> tool_call delta
    - legacy <think> 标签：若传入 legacy_think_parser，则拆分 thinking/answer delta
    """
    if token is None:
        return []

    deltas: list[StreamDelta] = []

    # 跳过 ToolMessage
    if getattr(token, "type", None) == "tool":
        return []

    # 1. 提取思考内容（LangChain 1.2.6 统一字段）
    reasoning_content = getattr(token, "reasoning_content", None)
    if reasoning_content and isinstance(reasoning_content, str):
        deltas.append(StreamDelta(kind=DeltaKind.THINKING, content=reasoning_content))

    # 2. 检查工具调用
    tool_call_chunks = getattr(token, "tool_call_chunks", None)
    if tool_call_chunks and isinstance(tool_call_chunks, list) and len(tool_call_chunks) > 0:
        chunk = tool_call_chunks[0]
        if isinstance(chunk, dict):
            deltas.append(StreamDelta(
                kind=DeltaKind.TOOL_CALL,
                tool_call_id=chunk.get("id"),
                tool_name=chunk.get("name"),
                tool_args=chunk.get("args") if isinstance(chunk.get("args"), dict) else None,
            ))
        return deltas

    tool_calls = getattr(token, "tool_calls", None)
    if tool_calls and isinstance(tool_calls, list) and len(tool_calls) > 0:
        call = tool_calls[0]
        if isinstance(call, dict):
            deltas.append(StreamDelta(
                kind=DeltaKind.TOOL_CALL,
                tool_call_id=call.get("id"),
                tool_name=call.get("name"),
                tool_args=call.get("args") if isinstance(call.get("args"), dict) else None,
            ))
        return deltas

    # 3. 提取回答内容（必要时兼容 legacy <think> 标签）
    content = getattr(token, "content", None)
    node = str((meta or {}).get("langgraph_node") or "")
    allow_answer_content = _should_stream_answer_content(node)
    if isinstance(content, str) and content:
        if node == "tools":
            deltas.append(StreamDelta(kind=DeltaKind.THINKING, content=content))
        elif allow_answer_content:
            if legacy_think_parser is None:
                deltas.append(StreamDelta(kind=DeltaKind.ANSWER, content=content))
            else:
                deltas.extend(legacy_think_parser.feed(content))
    elif isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            text = item.get("text", "")
            if not isinstance(text, str) or not text:
                continue
            if item_type in ("thinking", "reasoning"):
                deltas.append(StreamDelta(kind=DeltaKind.THINKING, content=text))
            elif item_type == "text" and allow_answer_content:
                if legacy_think_parser is None:
                    deltas.append(StreamDelta(kind=DeltaKind.ANSWER, content=text))
                else:
                    deltas.extend(legacy_think_parser.feed(text))

    return deltas


def strip_legacy_think_tags(text: str) -> str:
    """移除 <think>...</think> 思考段，未闭合则按正文保留。"""
    if not text:
        return ""

    open_tag = LegacyThinkParser._OPEN_TAG
    close_tag = LegacyThinkParser._CLOSE_TAG
    output: list[str] = []
    think_buffer: list[str] = []
    in_think = False
    pos = 0

    while True:
        next_open = text.find(open_tag, pos)
        next_close = text.find(close_tag, pos)
        if next_open == -1 and next_close == -1:
            break

        if next_open != -1 and (next_close == -1 or next_open < next_close):
            segment = text[pos:next_open]
            if in_think:
                think_buffer.append(segment)
            else:
                output.append(segment)
            in_think = True
            pos = next_open + len(open_tag)
            continue

        segment = text[pos:next_close]
        if in_think:
            think_buffer.append(segment)
            think_buffer = []
            in_think = False
        else:
            output.append(segment)
        pos = next_close + len(close_tag)

    tail = text[pos:]
    if in_think:
        think_buffer.append(tail)
        output.append("".join(think_buffer))
    else:
        output.append(tail)

    return "".join(output)


def extract_answer_text(content: object) -> str:
    """提取最终正文，剥离思考段与标签。"""
    if isinstance(content, str):
        return strip_legacy_think_tags(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(strip_legacy_think_tags(text))
        return "".join(parts)
    return ""


def build_think_delta(messages: list[Any]) -> StreamDelta | None:
    """从消息列表构建工具调用摘要的思考 delta。"""
    from langchain.messages import AIMessage, ToolMessage

    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                name = call.get("name", "unknown")
                args = call.get("args", {})
                parts.append(f"[工具调用] {name}: {args}")
        elif isinstance(msg, ToolMessage):
            content = msg.content
            if isinstance(content, str):
                parts.append(f"[工具结果] {msg.name}: {content[:200]}")

    if parts:
        return StreamDelta(kind=DeltaKind.THINKING, content="\n".join(parts))
    return None


@dataclass
class StreamState:
    messages: list[Any] = field(default_factory=list)
    pending_tool_calls: list[dict] = field(default_factory=list)
    stage_summaries: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    loop_counts: dict[str, Any] = field(default_factory=dict)
    best_answer: str | None = None
    best_answer_meta: dict[str, Any] | None = None
    human_approved: bool | None = None

    def apply_update(self, update: dict[str, Any]) -> None:
        """合并 LangGraph updates 中的 state 片段。"""
        if not isinstance(update, dict):
            return
        messages = update.get("messages")
        if isinstance(messages, list):
            self.messages.extend(messages)
        pending = update.get("pending_tool_calls")
        if isinstance(pending, list):
            self.pending_tool_calls = pending
        stage = update.get("stage_summaries")
        if isinstance(stage, dict):
            self.stage_summaries = stage
        metrics = update.get("metrics")
        if isinstance(metrics, dict):
            self.metrics = metrics
        loop_counts = update.get("loop_counts")
        if isinstance(loop_counts, dict):
            self.loop_counts = loop_counts
        best_answer = update.get("best_answer")
        if isinstance(best_answer, str):
            self.best_answer = best_answer
        best_answer_meta = update.get("best_answer_meta")
        if isinstance(best_answer_meta, dict):
            self.best_answer_meta = best_answer_meta
        if "human_approved" in update:
            self.human_approved = update.get("human_approved")

def extract_message_text(token: object) -> str:
    """从 LLM token chunk 中提取文本。"""
    if token is None:
        return ""
    text_attr = getattr(token, "text", None)
    if isinstance(text_attr, str):
        return text_attr
    content = getattr(token, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""

def apply_updates_chunk(state: StreamState, chunk: dict[str, Any]) -> list[Any]:
    """合并 updates chunk，返回 interrupt 列表。"""
    interrupts: list[Any] = []
    if not isinstance(chunk, dict):
        return interrupts
    for source, update in chunk.items():
        if source == "__interrupt__":
            if isinstance(update, list):
                interrupts.extend(update)
            continue
        if isinstance(update, dict):
            state.apply_update(update)
    return interrupts

async def stream_snapshots(
    fetcher: Callable[[], Awaitable[Any]],
    serializer: Callable[[Any], dict[str, Any]],
    is_terminal: Callable[[Any], bool],
    *,
    poll_interval: float = 1.0,
    request: object | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    """轮询数据并输出 update/final 事件。"""
    last_payload: dict[str, Any] | None = None
    while True:
        item = await fetcher()
        if item is None:
            yield "error", {"code": "NOT_FOUND", "message": "任务不存在"}
            return
        payload = serializer(item)
        if payload != last_payload:
            yield "update", payload
            last_payload = payload
        if is_terminal(item):
            yield "final", payload
            return
        if request is not None:
            is_disconnected = getattr(request, "is_disconnected", None)
            if callable(is_disconnected) and await is_disconnected():
                return
        await asyncio.sleep(poll_interval)

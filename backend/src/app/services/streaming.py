from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Awaitable, Callable

from app.services.message_normalizer import extract_text_content


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
    "doc_gate_precheck",
    "doc_grader_llm",
    "doc_gate_route",
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


def _should_stream_answer_content(node: str) -> bool:
    """Return whether raw text from a node should be treated as answer content."""
    if not node:
        return True
    if node == "tools":
        return False
    return node not in _NON_ANSWER_STREAM_NODES


def _extract_summary_text(summary: object) -> str:
    if not isinstance(summary, list):
        return ""
    parts: list[str] = []
    for item in summary:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "".join(parts)


def _extract_reasoning_from_block(block: object) -> list[str]:
    if not isinstance(block, dict):
        return []

    item_type = block.get("type")
    if not isinstance(item_type, str):
        return []

    candidates: list[str] = []
    if item_type == "thinking":
        thinking = block.get("thinking")
        if isinstance(thinking, str) and thinking:
            candidates.append(thinking)
        text = block.get("text")
        if isinstance(text, str) and text:
            candidates.append(text)
    elif item_type == "reasoning":
        reasoning = block.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            candidates.append(reasoning)
        summary_text = _extract_summary_text(block.get("summary"))
        if summary_text:
            candidates.append(summary_text)
        text = block.get("text")
        if isinstance(text, str) and text:
            candidates.append(text)
    return candidates


def _extract_reasoning_contents(token: object) -> list[str]:
    contents: list[str] = []

    # 1) LangChain unified field: reasoning_content
    reasoning_content = getattr(token, "reasoning_content", None)
    if isinstance(reasoning_content, str) and reasoning_content:
        contents.append(reasoning_content)

    # 2) Provider-specific additional_kwargs.reasoning
    additional_kwargs = getattr(token, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        reasoning = additional_kwargs.get("reasoning")
        if isinstance(reasoning, dict):
            reason_text = reasoning.get("reasoning")
            if isinstance(reason_text, str) and reason_text:
                contents.append(reason_text)
            summary_text = _extract_summary_text(reasoning.get("summary"))
            if summary_text:
                contents.append(summary_text)

    # 3) Standard content blocks (LangChain v1)
    try:
        content_blocks = getattr(token, "content_blocks", None)
    except Exception:
        content_blocks = None
    if isinstance(content_blocks, list):
        for block in content_blocks:
            contents.extend(_extract_reasoning_from_block(block))

    # 4) Raw content list fallback
    content = getattr(token, "content", None)
    if isinstance(content, list):
        for item in content:
            contents.extend(_extract_reasoning_from_block(item))

    # De-duplicate while preserving order.
    deduped: list[str] = []
    seen: set[str] = set()
    for text in contents:
        if text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def extract_stream_delta(
    token: object,
    meta: dict[str, Any] | None = None,
) -> list[StreamDelta]:
    """从 LLM token chunk 提取结构化 StreamDelta 列表。

    解析规则（LangChain 1.2.6 标准）：
    - reasoning_content -> thinking delta
    - content (str/list[text]) -> answer delta
    - tool_calls/tool_call_chunks -> tool_call delta
    """
    if token is None:
        return []

    deltas: list[StreamDelta] = []

    # 跳过 ToolMessage
    if getattr(token, "type", None) == "tool":
        return []

    # 1. 提取思考内容（兼容 LangChain 标准块与 provider-specific 结构）
    for reasoning_text in _extract_reasoning_contents(token):
        deltas.append(StreamDelta(kind=DeltaKind.THINKING, content=reasoning_text))

    # 2. 检查工具调用
    tool_call_chunks = getattr(token, "tool_call_chunks", None)
    if tool_call_chunks and isinstance(tool_call_chunks, list) and len(tool_call_chunks) > 0:
        for chunk in tool_call_chunks:
            if not isinstance(chunk, dict):
                continue
            raw_args = chunk.get("args")
            tool_args: dict[str, Any] | None = None
            if isinstance(raw_args, dict):
                tool_args = raw_args
            elif isinstance(raw_args, str):
                try:
                    parsed = json.loads(raw_args)
                except Exception:
                    parsed = None
                if isinstance(parsed, dict):
                    tool_args = parsed
            deltas.append(
                StreamDelta(
                    kind=DeltaKind.TOOL_CALL,
                    tool_call_id=chunk.get("id"),
                    tool_name=chunk.get("name"),
                    tool_args=tool_args,
                )
            )
    if any(delta.kind == DeltaKind.TOOL_CALL for delta in deltas):
        return deltas

    tool_calls = getattr(token, "tool_calls", None)
    if tool_calls and isinstance(tool_calls, list) and len(tool_calls) > 0:
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            deltas.append(
                StreamDelta(
                    kind=DeltaKind.TOOL_CALL,
                    tool_call_id=call.get("id"),
                    tool_name=call.get("name"),
                    tool_args=call.get("args")
                    if isinstance(call.get("args"), dict)
                    else None,
                )
            )
    if any(delta.kind == DeltaKind.TOOL_CALL for delta in deltas):
        return deltas

    # 3. 提取回答内容（必要时兼容 legacy <think> 标签）
    content = getattr(token, "content", None)
    node = str((meta or {}).get("langgraph_node") or "")
    allow_answer_content = _should_stream_answer_content(node)

    answer_texts: list[str] = []
    content_blocks = getattr(token, "content_blocks", None)
    if isinstance(content_blocks, list):
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").strip().lower()
            if block_type not in {"text", "output_text"}:
                continue
            text = block.get("text")
            if isinstance(text, str) and text:
                answer_texts.append(text)

    if isinstance(content, str) and content and not answer_texts:
        if node == "tools":
            deltas.append(StreamDelta(kind=DeltaKind.THINKING, content=content))
        elif allow_answer_content:
            deltas.append(StreamDelta(kind=DeltaKind.ANSWER, content=content))
    elif not answer_texts and isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") in {"text", "output_text"} and allow_answer_content:
                text = item.get("text")
                if not isinstance(text, str) or not text:
                    continue
                answer_texts.append(text)

    if allow_answer_content:
        for text in answer_texts:
            deltas.append(StreamDelta(kind=DeltaKind.ANSWER, content=text))

    return deltas


def extract_answer_text(content: object) -> str:
    """提取最终正文（优先标准文本内容块）。"""
    return extract_text_content(content, include_output_text=True)


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
    return extract_text_content(content, include_output_text=True)

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

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_think_tags(text: str) -> str:
    """移除 <think>...</think> 区段。"""
    return THINK_TAG_RE.sub("", text).strip()


@dataclass
class StreamState:
    messages: list[Any] = field(default_factory=list)
    pending_tool_calls: list[dict] = field(default_factory=list)
    stage_summaries: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
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
        if "human_approved" in update:
            self.human_approved = update.get("human_approved")

def extract_message_text(token: object) -> str:
    """从 LLM token chunk 中提取文本。"""
    if token is None:
        return ""
    text_attr = getattr(token, "text", None)
    if callable(text_attr):
        text = text_attr()
        if isinstance(text, str):
            return text
    elif isinstance(text_attr, str):
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

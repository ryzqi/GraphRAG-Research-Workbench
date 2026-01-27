"""DeepAgents 输入输出适配工具。"""

from __future__ import annotations

from typing import Any


def build_user_messages(text: str) -> dict[str, list[dict[str, str]]]:
    """构造 DeepAgents messages 输入。"""
    if not isinstance(text, str):
        raise TypeError("DeepAgents messages content must be a string.")
    return {"messages": [{"role": "user", "content": text}]}


def extract_last_message_text(result: object) -> str:
    """从 DeepAgents 返回中严格提取最后一条消息内容。"""
    if not isinstance(result, dict):
        raise TypeError("DeepAgents result must be a dict with a 'messages' list.")

    messages = result.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("DeepAgents result must include a non-empty 'messages' list.")

    last = messages[-1]
    content: Any
    if hasattr(last, "content"):
        content = getattr(last, "content")
    elif isinstance(last, dict) and "content" in last:
        content = last["content"]
    else:
        raise TypeError("DeepAgents last message must include 'content'.")

    if not isinstance(content, str):
        raise TypeError("DeepAgents message content must be a string.")
    return content

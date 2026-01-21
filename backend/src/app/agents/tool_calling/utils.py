"""Tool calling 通用工具：命名空间、截断、消息抽取。

说明：该模块尽量只依赖 LangChain 消息类型与本项目的 ToolMeta，避免在 Graph/Service 间产生
重复的解析与映射逻辑。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Sequence

from langchain.messages import AIMessage, AnyMessage, ToolMessage

if TYPE_CHECKING:
    from .registry import ToolMeta

MCP_TOOL_PREFIX = "mcp__"
DEFAULT_TOOL_OUTPUT_MAX_CHARS = 8000
TRUNCATION_MARK = "\n\n（输出已截断）"

_TOOL_TOKEN_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def _sanitize_tool_token(token: str) -> str:
    token = token.strip()
    if not token:
        return "tool"
    return _TOOL_TOKEN_RE.sub("_", token)



def make_mcp_tool_name(extension_id: str, tool_name: str) -> str:
    """生成 MCP 工具的命名空间名称。

    规则：`mcp__{extension_id}__{tool_name}`，并做最小化字符清洗以满足工具名约束。
    """
    ext = _sanitize_tool_token(extension_id)
    raw = _sanitize_tool_token(tool_name)
    return f"{MCP_TOOL_PREFIX}{ext}__{raw}"


def is_mcp_tool_name(name: str) -> bool:
    return name.startswith(MCP_TOOL_PREFIX) and "__" in name[len(MCP_TOOL_PREFIX) :]


def parse_mcp_tool_name(name: str) -> tuple[str, str] | None:
    """解析 MCP 命名空间工具名，返回 (extension_id, raw_tool_name)。"""
    if not name.startswith(MCP_TOOL_PREFIX):
        return None
    rest = name[len(MCP_TOOL_PREFIX) :]
    parts = rest.split("__", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]



def truncate_tool_output(
    text: str, max_chars: int = DEFAULT_TOOL_OUTPUT_MAX_CHARS
) -> tuple[str, bool]:
    """截断工具输出，避免 ToolMessage 过长。

    返回 (处理后的文本, 是否截断)。
    """
    if max_chars <= 0:
        return "", True
    if len(text) <= max_chars:
        return text, False

    marker = TRUNCATION_MARK
    budget = max(max_chars - len(marker), 0)
    truncated = text[:budget].rstrip()
    return f"{truncated}{marker}", True


def _stringify(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, ensure_ascii=False)
    except TypeError:
        return str(obj)


def _get_last_ai_message(messages: Sequence[AnyMessage]) -> AIMessage | None:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return msg
    return None



def extract_pending_tool_calls(
    messages: Sequence[AnyMessage],
    tool_meta_by_name: dict[str, ToolMeta],
    *,
    external_only: bool = True,
) -> list[dict]:
    """从最后一个 AIMessage 中提取待审批工具调用（用于 interrupt payload）。"""
    ai = _get_last_ai_message(messages)
    if ai is None:
        return []

    calls = getattr(ai, "tool_calls", None) or []
    pending: list[dict] = []
    for call in calls:
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
        args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
        if not name or not isinstance(name, str):
            continue

        meta = tool_meta_by_name.get(name)
        if meta is None:
            continue
        if external_only and not meta.is_external:
            continue

        pending.append(
            {
                "extension_id": meta.extension_id,
                "extension_name": meta.extension_name,
                "tool_name": meta.raw_tool_name,
                "args": args if isinstance(args, dict) else {},
                "is_builtin": meta.is_builtin,
            }
        )

    return pending


def extract_tool_results(
    messages: Sequence[AnyMessage],
    tool_meta_by_name: dict[str, ToolMeta],
) -> list[dict]:
    """从 messages 中提取工具执行结果，供服务层审计/落库。"""
    tool_msgs: dict[str, ToolMessage] = {}
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_msgs[str(msg.tool_call_id)] = msg

    results: list[dict] = []
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        calls = getattr(msg, "tool_calls", None) or []
        for call in calls:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
            call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
            if not name or not isinstance(name, str) or not call_id:
                continue

            meta = tool_meta_by_name.get(name)
            if meta is None:
                continue

            tool_msg = tool_msgs.get(str(call_id))
            if tool_msg is None:
                continue

            success = getattr(tool_msg, "status", "success") == "success"
            output = _stringify(tool_msg.content)
            results.append(
                {
                    "extension_id": meta.extension_id,
                    "extension_name": meta.extension_name,
                    "tool_name": meta.raw_tool_name,
                    "args": args if isinstance(args, dict) else {},
                    "is_builtin": meta.is_builtin,
                    "success": success,
                    "output": output,
                }
            )

    return results

"""基于 ToolNode 的统一工具调用编排。

该包提供：
- 统一的 ToolCallingGraphBuilder（model -> tools -> model 循环，可选人工审批）
- 工具注册与命名空间（尤其是 MCP 扩展工具）
- ToolMessage/ToolCall 的抽取与审计辅助
"""

from .builder import ToolCallingGraphBuilder
from .registry import ToolMeta, build_tool_registry
from .utils import (
    extract_pending_tool_calls,
    extract_tool_results,
    is_mcp_tool_name,
    make_mcp_tool_name,
    parse_mcp_tool_name,
    truncate_tool_output,
)

__all__ = [
    "ToolCallingGraphBuilder",
    "ToolMeta",
    "build_tool_registry",
    "extract_pending_tool_calls",
    "extract_tool_results",
    "is_mcp_tool_name",
    "make_mcp_tool_name",
    "parse_mcp_tool_name",
    "truncate_tool_output",
]

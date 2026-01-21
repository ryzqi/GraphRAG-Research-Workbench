"""MCP 适配器（基于 langchain-mcp-adapters）。"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from typing import Iterable

from langchain.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.logging import get_logger
from app.core.settings import Settings
from app.models.tool_extension import ExtensionTransport, ToolExtension

logger = get_logger(__name__)

# MCP 命令白名单（仅允许执行这些命令）
_ALLOWED_MCP_COMMANDS = frozenset({
    "npx",
    "node",
    "python",
    "python3",
    "uvx",
})

# 危险字符检测模式
_DANGEROUS_CHARS = re.compile(r"[;&|`$]")


@dataclass(frozen=True, slots=True)
class McpToolEntry:
    """MCP 工具条目（保留扩展与原始工具名）。"""

    extension: ToolExtension
    tool: BaseTool
    raw_tool_name: str


def _parse_stdio_endpoint(endpoint: str) -> tuple[str, list[str]]:
    endpoint = endpoint.strip()
    if not endpoint:
        raise ValueError("无效的 stdio 端点")
    if _DANGEROUS_CHARS.search(endpoint):
        raise ValueError("端点包含危险字符")

    try:
        parts = shlex.split(endpoint)
    except ValueError as exc:  # pragma: no cover
        raise ValueError(f"无效的 stdio 端点: {exc}") from exc

    if not parts:
        raise ValueError("无效的 stdio 端点")

    raw = os.path.basename(parts[0])
    cmd, _ = os.path.splitext(raw)
    if cmd.lower() not in _ALLOWED_MCP_COMMANDS:
        raise ValueError(f"不允许的 MCP 命令: {raw}")

    return parts[0], parts[1:]


def _parse_scope(scope: dict | None) -> tuple[dict[str, str], dict[str, str], bool]:
    headers: dict[str, str] = {}
    env: dict[str, str] = {}
    prefer_streamable = False
    if not scope:
        return headers, env, prefer_streamable

    raw_headers = scope.get("headers")
    if isinstance(raw_headers, dict):
        for key, value in raw_headers.items():
            if key and value is not None:
                headers[str(key)] = str(value)

    raw_env = scope.get("env")
    if isinstance(raw_env, dict):
        for key, value in raw_env.items():
            if key and value is not None:
                env[str(key)] = str(value)

    auth = scope.get("auth")
    if isinstance(auth, dict):
        auth_type = str(auth.get("type", "")).lower()
        token = auth.get("token")
        if token:
            token_value = str(token)
            if auth_type == "bearer":
                headers.setdefault("Authorization", f"Bearer {token_value}")
            elif auth_type == "basic":
                headers.setdefault("Authorization", f"Basic {token_value}")

    protocol = scope.get("protocol")
    if isinstance(protocol, str):
        protocol_lower = protocol.lower()
        if protocol_lower in {"streamable_http", "streamable-http"}:
            prefer_streamable = True
        elif protocol_lower == "jsonrpc":
            logger.warning(
                "MCP scope.protocol=jsonrpc 已不再支持，已回退为 http/streamable_http"
            )

    return headers, env, prefer_streamable


def build_mcp_server_params(
    extension: ToolExtension, settings: Settings
) -> dict[str, object]:
    """将 ToolExtension 转换为 MultiServerMCPClient 连接参数。"""
    headers, env, prefer_streamable = _parse_scope(extension.scope)
    transport = extension.transport

    if transport == ExtensionTransport.HTTP:
        use_streamable = bool(settings.mcp_streamable_http or prefer_streamable)
        params: dict[str, object] = {
            "transport": "streamable_http" if use_streamable else "http",
            "url": extension.endpoint,
        }
        if headers:
            params["headers"] = headers
        params["timeout"] = settings.mcp_http_timeout_seconds
        return params

    if transport == ExtensionTransport.STDIO:
        command, args = _parse_stdio_endpoint(extension.endpoint)
        params = {"transport": "stdio", "command": command, "args": args}
        if env:
            params["env"] = env
        return params

    raise ValueError(f"不支持的传输类型: {extension.transport}")


def build_mcp_connections(
    extensions: Iterable[ToolExtension], settings: Settings
) -> dict[str, dict[str, object]]:
    """批量构建 MCP 连接配置。"""
    connections: dict[str, dict[str, object]] = {}
    for ext in extensions:
        try:
            connections[str(ext.id)] = build_mcp_server_params(ext, settings)
        except ValueError as exc:
            logger.warning(
                "MCP 扩展配置无效，已跳过",
                extra={"extension_id": str(ext.id), "error": str(exc)},
            )
    return connections


async def load_mcp_tools(
    *, settings: Settings, extensions: Iterable[ToolExtension]
) -> list[McpToolEntry]:
    """加载 MCP 工具列表（按扩展分组）。"""
    extensions_list = list(extensions)
    if not settings.mcp_enabled or not extensions_list:
        return []

    connections = build_mcp_connections(extensions_list, settings)
    if not connections:
        return []

    client = MultiServerMCPClient(connections, tool_name_prefix=False)
    entries: list[McpToolEntry] = []
    for ext in extensions_list:
        server_name = str(ext.id)
        if server_name not in connections:
            continue
        try:
            tools = await client.get_tools(server_name=server_name)
        except Exception as exc:  # pragma: no cover - 依赖外部 MCP
            logger.warning(
                "加载 MCP 工具失败",
                extra={"extension_id": server_name, "error": str(exc)},
            )
            continue
        for tool in tools:
            entries.append(
                McpToolEntry(extension=ext, tool=tool, raw_tool_name=tool.name)
            )
    return entries


def tool_input_schema(tool: BaseTool) -> dict | None:
    """提取工具的输入 JSON Schema。"""
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is None:
        return None
    if hasattr(args_schema, "model_json_schema"):
        return args_schema.model_json_schema()
    if hasattr(args_schema, "schema"):
        return args_schema.schema()
    return None

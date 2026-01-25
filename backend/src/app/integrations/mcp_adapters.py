"""MCP 适配器（基于 langchain-mcp-adapters）。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

from langchain.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest, ToolCallInterceptor
from mcp.types import CallToolResult, TextContent

from app.core.logging import get_logger
from app.core.logging import redact_dict
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

_SCOPE_TOOL_ALLOWLIST_KEYS = ("tools_allowlist", "tool_allowlist", "allow_tools")
_MAX_TOOL_ARGS_BYTES = 32 * 1024
_MAX_AUDIT_SNIPPET_CHARS = 2000


@dataclass(frozen=True, slots=True)
class McpToolEntry:
    """MCP 工具条目（保留扩展与原始工具名）。"""

    extension: ToolExtension
    tool: BaseTool
    raw_tool_name: str


def _format_audit_payload(payload: object, max_chars: int = _MAX_AUDIT_SNIPPET_CHARS) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except TypeError:
        text = str(payload)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}…"


def _parse_tool_allowlist(scope: dict | None) -> set[str] | None:
    if not scope:
        return None
    value: object | None = None
    for key in _SCOPE_TOOL_ALLOWLIST_KEYS:
        if key in scope:
            value = scope.get(key)
            break
    if value is None:
        return None
    if isinstance(value, str):
        items = [v.strip() for v in value.split(",") if v.strip()]
        return set(items) or None
    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
        return set(items) or None
    return None


class McpToolCallAuditInterceptor(ToolCallInterceptor):
    """MCP 工具调用拦截器：安全校验 + 审计 + 超时/降级。

    注意：该拦截器只能拿到 tool_name/args/server_name，因此降级以“返回可读文本结果”的方式完成，
    不依赖 ToolMessage（缺少 tool_call_id）。
    """

    def __init__(
        self,
        *,
        settings: Settings,
        allow_external: bool,
        extensions_by_id: dict[str, ToolExtension],
    ) -> None:
        self._settings = settings
        self._allow_external = allow_external
        self._extensions_by_id = extensions_by_id
        self._allowlist_by_server: dict[str, set[str] | None] = {
            ext_id: _parse_tool_allowlist(ext.scope)
            for ext_id, ext in extensions_by_id.items()
        }
        self._timeout_by_server: dict[str, int] = {}
        for ext_id, ext in extensions_by_id.items():
            if ext.transport == ExtensionTransport.STDIO:
                self._timeout_by_server[ext_id] = int(settings.mcp_stdio_timeout_seconds)
            else:
                self._timeout_by_server[ext_id] = int(settings.mcp_http_timeout_seconds)

    async def __call__(
        self,
        request: MCPToolCallRequest,
        handler: Callable[[MCPToolCallRequest], Awaitable[object]],
    ) -> object:
        ext = self._extensions_by_id.get(request.server_name)
        timeout_seconds = self._timeout_by_server.get(
            request.server_name, int(self._settings.mcp_http_timeout_seconds)
        )

        if not self._settings.mcp_enabled:
            logger.info(
                "MCP disabled, skip tool call",
                extra={
                    "extension_id": request.server_name,
                    "tool_name": request.name,
                },
            )
            return CallToolResult(
                content=[TextContent(type="text", text="MCP 未启用，已跳过外部工具调用。")],
                isError=False,
            )

        if not self._allow_external:
            logger.warning(
                "External tools disabled, skip MCP tool call",
                extra={
                    "extension_id": request.server_name,
                    "extension_name": getattr(ext, "name", None),
                    "tool_name": request.name,
                },
            )
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="外部工具调用已禁用（allow_external=false），已跳过 MCP 工具调用。",
                    )
                ],
                isError=False,
            )

        allowlist = self._allowlist_by_server.get(request.server_name)
        if allowlist and request.name not in allowlist:
            logger.warning(
                "MCP tool blocked by allowlist",
                extra={
                    "extension_id": request.server_name,
                    "extension_name": getattr(ext, "name", None),
                    "tool_name": request.name,
                },
            )
            return CallToolResult(
                content=[
                    TextContent(type="text", text="该 MCP 工具未在 allowlist 中，已跳过执行。")
                ],
                isError=False,
            )

        # 参数校验：必须可 JSON 序列化，且避免超大 payload
        try:
            args_bytes = json.dumps(request.args, ensure_ascii=False, default=str).encode(
                "utf-8"
            )
        except TypeError as exc:
            logger.warning(
                "Invalid MCP tool args, skip tool call",
                extra={
                    "extension_id": request.server_name,
                    "extension_name": getattr(ext, "name", None),
                    "tool_name": request.name,
                    "error": str(exc),
                },
            )
            return CallToolResult(
                content=[TextContent(type="text", text="MCP 工具参数无效，已跳过执行。")],
                isError=False,
            )

        if len(args_bytes) > _MAX_TOOL_ARGS_BYTES:
            logger.warning(
                "MCP tool args too large, skip tool call",
                extra={
                    "extension_id": request.server_name,
                    "extension_name": getattr(ext, "name", None),
                    "tool_name": request.name,
                    "args_bytes": len(args_bytes),
                },
            )
            return CallToolResult(
                content=[TextContent(type="text", text="MCP 工具参数过大，已跳过执行。")],
                isError=False,
            )

        logger.info(
            "MCP tool call start",
            extra={
                "extension_id": request.server_name,
                "extension_name": getattr(ext, "name", None),
                "tool_name": request.name,
                "args": _format_audit_payload(redact_dict(request.args)),
                "timeout_seconds": timeout_seconds,
            },
        )

        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(handler(request), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.warning(
                "MCP tool call timeout, degraded",
                extra={
                    "extension_id": request.server_name,
                    "extension_name": getattr(ext, "name", None),
                    "tool_name": request.name,
                    "elapsed_ms": elapsed_ms,
                },
            )
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"MCP 工具调用超时（{timeout_seconds}s），已跳过该工具。",
                    )
                ],
                isError=False,
            )
        except asyncio.CancelledError:
            logger.info(
                "MCP tool call canceled",
                extra={
                    "extension_id": request.server_name,
                    "extension_name": getattr(ext, "name", None),
                    "tool_name": request.name,
                },
            )
            raise
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.warning(
                "MCP tool call failed, degraded",
                extra={
                    "extension_id": request.server_name,
                    "extension_name": getattr(ext, "name", None),
                    "tool_name": request.name,
                    "elapsed_ms": elapsed_ms,
                    "error": str(exc),
                },
            )
            return CallToolResult(
                content=[TextContent(type="text", text="MCP 工具调用失败，已跳过该工具。")],
                isError=False,
            )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        structured = getattr(result, "structuredContent", None)
        structured_keys: list[str] | None = None
        if isinstance(structured, dict):
            structured_keys = list(structured.keys())[:50]

        logger.info(
            "MCP tool call end",
            extra={
                "extension_id": request.server_name,
                "extension_name": getattr(ext, "name", None),
                "tool_name": request.name,
                "elapsed_ms": elapsed_ms,
                "structured_keys": structured_keys,
            },
        )
        return result


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
    *,
    settings: Settings,
    extensions: Iterable[ToolExtension],
    allow_external: bool = True,
) -> list[McpToolEntry]:
    """加载 MCP 工具列表（按扩展分组）。"""
    extensions_list = list(extensions)
    if not settings.mcp_enabled or not extensions_list:
        return []

    connections = build_mcp_connections(extensions_list, settings)
    if not connections:
        return []

    extensions_by_id = {str(ext.id): ext for ext in extensions_list}
    client = MultiServerMCPClient(
        connections,
        tool_name_prefix=False,
        tool_interceptors=[
            McpToolCallAuditInterceptor(
                settings=settings,
                allow_external=allow_external,
                extensions_by_id=extensions_by_id,
            )
        ],
    )
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

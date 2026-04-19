"""MCP 适配器（基于 langchain-mcp-adapters）。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Awaitable, Callable, Iterable, TypeAlias

from langchain.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest, ToolCallInterceptor
from langchain_mcp_adapters.sessions import (
    SSEConnection,
    StdioConnection,
    StreamableHttpConnection,
    WebsocketConnection,
)
from langchain_mcp_adapters.tools import load_mcp_tools as load_langchain_mcp_tools
from mcp.types import CallToolResult, TextContent

from app.core.logging import redact_dict
from app.core.settings import Settings
from app.models.tool_extension import ExtensionTransport, ToolExtension

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

# 危险字符检测模式
_DANGEROUS_CHARS = re.compile(r"[;&|`$<>]")
_MAX_TOOL_ARGS_BYTES = 32 * 1024
_MAX_AUDIT_SNIPPET_CHARS = 2000
_MAX_STDIO_ARG_CHARS = 512
_MAX_STDIO_ARGS = 64

McpConnection: TypeAlias = (
    StdioConnection | SSEConnection | StreamableHttpConnection | WebsocketConnection
)


@dataclass(frozen=True, slots=True)
class McpToolEntry:
    """MCP 工具条目（保留扩展与原始工具名）。"""

    extension: ToolExtension
    tool: BaseTool
    raw_tool_name: str


@dataclass(frozen=True, slots=True)
class McpServerDiagnostics:
    """MCP 连接诊断信息。"""

    status: str
    last_error: str | None = None
    latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class _McpToolLoadResult:
    server_name: str
    entries: list[McpToolEntry]
    diagnostics: McpServerDiagnostics


@dataclass(slots=True)
class _OpenedMcpRuntime:
    server_name: str
    entries: list[McpToolEntry]
    diagnostics: McpServerDiagnostics
    session_context: object | None = None


def _format_audit_payload(
    payload: object, max_chars: int = _MAX_AUDIT_SNIPPET_CHARS
) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except TypeError:
        text = str(payload)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}…"


def _validate_stdio_token(value: str, *, field: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"无效的 stdio {field}")
    if "\n" in candidate or "\r" in candidate:
        raise ValueError(f"stdio {field} 包含换行符")
    if _DANGEROUS_CHARS.search(candidate):
        raise ValueError(f"stdio {field} 包含危险字符")
    if len(candidate) > _MAX_STDIO_ARG_CHARS:
        raise ValueError(f"stdio {field} 过长")
    return candidate


def _to_str_dict(value: object | None) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        k = str(key).strip()
        if not k:
            continue
        if item is None:
            continue
        result[k] = str(item)
    return result


def _resolve_timeout_seconds(extension: ToolExtension, settings: Settings) -> int:
    default_timeout = (
        int(settings.mcp_http_timeout_seconds)
        if extension.transport == ExtensionTransport.HTTP
        else int(settings.mcp_stdio_timeout_seconds)
    )
    if extension.transport == ExtensionTransport.HTTP:
        config = (
            extension.http_config if isinstance(extension.http_config, dict) else {}
        )
    else:
        config = (
            extension.stdio_config if isinstance(extension.stdio_config, dict) else {}
        )
    value = config.get("timeout_seconds")
    if value is None:
        return default_timeout
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return default_timeout
    return timeout if timeout > 0 else default_timeout


def _resolve_stdio_connection_config(
    extension: ToolExtension,
) -> tuple[str, list[str], dict[str, str], str | None]:
    config = (
        extension.stdio_config if isinstance(extension.stdio_config, dict) else None
    )
    if not isinstance(config, dict):
        raise ValueError("stdio_config 缺失")
    command = str(config.get("command", "")).strip()
    if not command:
        raise ValueError("stdio_config.command 不能为空")
    raw_args = config.get("args", [])
    if raw_args is None:
        raw_args = []
    if not isinstance(raw_args, list):
        raise ValueError("stdio_config.args 必须为数组")
    if len(raw_args) > _MAX_STDIO_ARGS:
        raise ValueError("stdio 参数数量过多")

    args: list[str] = []
    for index, item in enumerate(raw_args, start=1):
        args.append(_validate_stdio_token(str(item), field=f"args[{index}]"))

    env = _to_str_dict(config.get("env"))
    cwd_raw = config.get("cwd")
    cwd = None
    if cwd_raw is not None:
        cwd = str(cwd_raw).strip() or None
    return command, args, env, cwd


def _resolve_http_headers(extension: ToolExtension) -> tuple[str, dict[str, str]]:
    config = extension.http_config if isinstance(extension.http_config, dict) else None
    if not isinstance(config, dict):
        raise ValueError("http_config 缺失")
    url = str(config.get("url", "")).strip()
    if not url:
        raise ValueError("http_config.url 不能为空")
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("http_config.url 必须以 http:// 或 https:// 开头")

    protocol = str(config.get("protocol", "streamable_http")).strip().lower()
    if protocol not in {"streamable_http", "streamable-http"}:
        raise ValueError("仅支持 streamable_http 协议")

    headers = _to_str_dict(config.get("headers"))
    auth = config.get("auth")
    if isinstance(auth, dict):
        auth_type = str(auth.get("type", "none")).strip().lower()
        token = auth.get("token")
        if auth_type in {"bearer", "basic"} and token:
            prefix = "Bearer" if auth_type == "bearer" else "Basic"
            headers.setdefault("Authorization", f"{prefix} {str(token)}")
    return url, headers


class McpToolCallAuditInterceptor(ToolCallInterceptor):
    """MCP 工具调用拦截器：安全校验 + 审计 + 超时/降级。"""

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
        self._timeout_by_server: dict[str, int] = {
            ext_id: _resolve_timeout_seconds(ext, settings)
            for ext_id, ext in extensions_by_id.items()
        }

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
                content=[
                    TextContent(type="text", text="MCP 未启用，已跳过外部工具调用。")
                ],
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

        # 参数校验：必须可 JSON 序列化，且避免超大 payload
        try:
            args_bytes = json.dumps(
                request.args, ensure_ascii=False, default=str
            ).encode("utf-8")
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
                content=[
                    TextContent(type="text", text="MCP 工具参数无效，已跳过执行。")
                ],
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
                content=[
                    TextContent(type="text", text="MCP 工具参数过大，已跳过执行。")
                ],
                isError=False,
            )

        logger.info(
            "MCP tool call start",
            extra={
                "extension_id": request.server_name,
                "extension_name": getattr(ext, "name", None),
                "transport": getattr(ext.transport, "value", None) if ext else None,
                "tool_name": request.name,
                "tool_args": _format_audit_payload(redact_dict(request.args)),
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
                content=[
                    TextContent(type="text", text="MCP 工具调用失败，已跳过该工具。")
                ],
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


def build_mcp_server_params(
    extension: ToolExtension, settings: Settings
) -> McpConnection:
    """将 ToolExtension 转换为 MultiServerMCPClient 连接参数。"""
    transport = extension.transport

    if transport == ExtensionTransport.HTTP:
        url, headers = _resolve_http_headers(extension)
        http_params: StreamableHttpConnection = {
            "transport": "streamable_http",
            "url": url,
            "timeout": timedelta(seconds=_resolve_timeout_seconds(extension, settings)),
        }
        if headers:
            http_params["headers"] = headers
        return http_params

    if transport == ExtensionTransport.STDIO:
        command, args, env, cwd = _resolve_stdio_connection_config(extension)
        stdio_params: StdioConnection = {
            "transport": "stdio",
            "command": command,
            "args": args,
        }
        if env:
            stdio_params["env"] = env
        if cwd:
            stdio_params["cwd"] = cwd
        return stdio_params

    raise ValueError(f"不支持的传输类型: {extension.transport}")


def build_mcp_connections(
    extensions: Iterable[ToolExtension], settings: Settings
) -> dict[str, McpConnection]:
    """批量构建 MCP 连接配置。"""
    connections: dict[str, McpConnection] = {}
    for ext in extensions:
        try:
            connections[str(ext.id)] = build_mcp_server_params(ext, settings)
        except ValueError as exc:
            logger.warning(
                "MCP 扩展配置无效，已跳过",
                extra={"extension_id": str(ext.id), "error": str(exc)},
            )
    return connections


def _invalid_extension_diagnostics() -> McpServerDiagnostics:
    return McpServerDiagnostics(
        status="failed",
        last_error="扩展配置无效",
        latency_ms=None,
    )


def _build_tool_interceptors(
    *,
    settings: Settings,
    allow_external: bool,
    extensions_by_id: dict[str, ToolExtension],
) -> list[ToolCallInterceptor]:
    return [
        McpToolCallAuditInterceptor(
            settings=settings,
            allow_external=allow_external,
            extensions_by_id=extensions_by_id,
        )
    ]


async def _load_single_mcp_tools(
    *,
    client: MultiServerMCPClient,
    extension: ToolExtension,
    connections: dict[str, McpConnection],
) -> _McpToolLoadResult:
    server_name = str(extension.id)
    if server_name not in connections:
        return _McpToolLoadResult(
            server_name=server_name,
            entries=[],
            diagnostics=_invalid_extension_diagnostics(),
        )

    start = time.perf_counter()
    try:
        tools = await client.get_tools(server_name=server_name)
    except Exception as exc:  # pragma: no cover - 依赖外部 MCP
        latency_ms = int((time.perf_counter() - start) * 1000)
        diagnostics = McpServerDiagnostics(
            status="failed",
            last_error=str(exc),
            latency_ms=latency_ms,
        )
        logger.warning(
            "加载 MCP 工具失败",
            extra={
                "extension_id": server_name,
                "error": str(exc),
                "latency_ms": latency_ms,
            },
        )
        return _McpToolLoadResult(
            server_name=server_name,
            entries=[],
            diagnostics=diagnostics,
        )

    latency_ms = int((time.perf_counter() - start) * 1000)
    if not tools:
        return _McpToolLoadResult(
            server_name=server_name,
            entries=[],
            diagnostics=McpServerDiagnostics(
                status="degraded",
                last_error="未发现可用工具",
                latency_ms=latency_ms,
            ),
        )

    return _McpToolLoadResult(
        server_name=server_name,
        entries=[
            McpToolEntry(extension=extension, tool=tool, raw_tool_name=tool.name)
            for tool in tools
        ],
        diagnostics=McpServerDiagnostics(
            status="ok",
            last_error=None,
            latency_ms=latency_ms,
        ),
    )


async def _open_single_mcp_runtime(
    *,
    settings: Settings,
    extension: ToolExtension,
    connections: dict[str, McpConnection],
    allow_external: bool,
    extensions_by_id: dict[str, ToolExtension],
) -> _OpenedMcpRuntime:
    server_name = str(extension.id)
    if server_name not in connections:
        return _OpenedMcpRuntime(
            server_name=server_name,
            entries=[],
            diagnostics=_invalid_extension_diagnostics(),
        )

    client = MultiServerMCPClient(
        {server_name: connections[server_name]},
        tool_name_prefix=False,
        tool_interceptors=_build_tool_interceptors(
            settings=settings,
            allow_external=allow_external,
            extensions_by_id=extensions_by_id,
        ),
    )
    session_context = client.session(server_name)
    start = time.perf_counter()
    try:
        session = await session_context.__aenter__()
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.perf_counter() - start) * 1000)
        diagnostics = McpServerDiagnostics(
            status="failed",
            last_error=str(exc),
            latency_ms=latency_ms,
        )
        logger.warning(
            "加载 MCP 工具失败",
            extra={
                "extension_id": server_name,
                "error": str(exc),
                "latency_ms": latency_ms,
            },
        )
        return _OpenedMcpRuntime(
            server_name=server_name,
            entries=[],
            diagnostics=diagnostics,
        )

    try:
        tools = await load_langchain_mcp_tools(
            session,
            callbacks=client.callbacks,
            tool_interceptors=client.tool_interceptors,
            server_name=server_name,
            tool_name_prefix=client.tool_name_prefix,
        )
    except Exception as exc:  # noqa: BLE001
        await session_context.__aexit__(type(exc), exc, exc.__traceback__)
        latency_ms = int((time.perf_counter() - start) * 1000)
        diagnostics = McpServerDiagnostics(
            status="failed",
            last_error=str(exc),
            latency_ms=latency_ms,
        )
        logger.warning(
            "加载 MCP 工具失败",
            extra={
                "extension_id": server_name,
                "error": str(exc),
                "latency_ms": latency_ms,
            },
        )
        return _OpenedMcpRuntime(
            server_name=server_name,
            entries=[],
            diagnostics=diagnostics,
        )

    latency_ms = int((time.perf_counter() - start) * 1000)
    if not tools:
        await session_context.__aexit__(None, None, None)
        return _OpenedMcpRuntime(
            server_name=server_name,
            entries=[],
            diagnostics=McpServerDiagnostics(
                status="degraded",
                last_error="未发现可用工具",
                latency_ms=latency_ms,
            ),
        )

    return _OpenedMcpRuntime(
        server_name=server_name,
        entries=[
            McpToolEntry(extension=extension, tool=tool, raw_tool_name=tool.name)
            for tool in tools
        ],
        diagnostics=McpServerDiagnostics(
            status="ok",
            last_error=None,
            latency_ms=latency_ms,
        ),
        session_context=session_context,
    )


async def load_mcp_tools_with_diagnostics(
    *,
    settings: Settings,
    extensions: Iterable[ToolExtension],
    allow_external: bool = True,
) -> tuple[list[McpToolEntry], dict[str, McpServerDiagnostics]]:
    """加载 MCP 工具列表并返回每个扩展的连接诊断。"""
    extensions_list = list(extensions)
    if not settings.mcp_enabled or not extensions_list:
        return [], {}

    connections = build_mcp_connections(extensions_list, settings)
    if not connections:
        diagnostics = {
            str(ext.id): McpServerDiagnostics(
                status="failed", last_error="扩展配置无效", latency_ms=None
            )
            for ext in extensions_list
        }
        return [], diagnostics

    extensions_by_id = {str(ext.id): ext for ext in extensions_list}
    client = MultiServerMCPClient(
        connections,
        tool_name_prefix=False,
        tool_interceptors=_build_tool_interceptors(
            settings=settings,
            allow_external=allow_external,
            extensions_by_id=extensions_by_id,
        ),
    )
    entries: list[McpToolEntry] = []
    diagnostics: dict[str, McpServerDiagnostics] = {}
    results: list[_McpToolLoadResult] = []
    parallel_load_enabled = bool(
        getattr(settings, "mcp_parallel_load_enabled", True)
    )
    if parallel_load_enabled:
        results = await asyncio.gather(
            *[
                _load_single_mcp_tools(
                    client=client,
                    extension=ext,
                    connections=connections,
                )
                for ext in extensions_list
            ]
        )
    else:
        for ext in extensions_list:
            results.append(
                await _load_single_mcp_tools(
                    client=client,
                    extension=ext,
                    connections=connections,
                )
            )

    for result in results:
        diagnostics[result.server_name] = result.diagnostics
        entries.extend(result.entries)
    return entries, diagnostics


async def load_mcp_tools(
    *,
    settings: Settings,
    extensions: Iterable[ToolExtension],
    allow_external: bool = True,
) -> list[McpToolEntry]:
    """加载 MCP 工具列表（按扩展分组）。"""
    entries, _ = await load_mcp_tools_with_diagnostics(
        settings=settings,
        extensions=extensions,
        allow_external=allow_external,
    )
    return entries


@asynccontextmanager
async def open_mcp_tool_runtime(
    *,
    settings: Settings,
    extensions: Iterable[ToolExtension],
    allow_external: bool = True,
) -> AsyncIterator[tuple[list[McpToolEntry], dict[str, McpServerDiagnostics]]]:
    """为单次 agent 运行打开可复用的 MCP session，并在退出时统一关闭。"""
    extensions_list = list(extensions)
    if not settings.mcp_enabled or not extensions_list:
        yield [], {}
        return

    connections = build_mcp_connections(extensions_list, settings)
    if not connections:
        diagnostics = {
            str(ext.id): McpServerDiagnostics(
                status="failed", last_error="扩展配置无效", latency_ms=None
            )
            for ext in extensions_list
        }
        yield [], diagnostics
        return

    extensions_by_id = {str(ext.id): ext for ext in extensions_list}
    entries: list[McpToolEntry] = []
    diagnostics: dict[str, McpServerDiagnostics] = {}

    async with AsyncExitStack() as stack:
        runtimes: list[_OpenedMcpRuntime] = []
        parallel_load_enabled = bool(
            getattr(settings, "mcp_parallel_load_enabled", True)
        )
        if parallel_load_enabled:
            runtimes = await asyncio.gather(
                *[
                    _open_single_mcp_runtime(
                        settings=settings,
                        extension=ext,
                        connections=connections,
                        allow_external=allow_external,
                        extensions_by_id=extensions_by_id,
                    )
                    for ext in extensions_list
                ]
            )
        else:
            for ext in extensions_list:
                runtimes.append(
                    await _open_single_mcp_runtime(
                        settings=settings,
                        extension=ext,
                        connections=connections,
                        allow_external=allow_external,
                        extensions_by_id=extensions_by_id,
                    )
                )

        for runtime in runtimes:
            diagnostics[runtime.server_name] = runtime.diagnostics
            entries.extend(runtime.entries)
            if runtime.session_context is not None:
                stack.push_async_exit(runtime.session_context)

        yield entries, diagnostics


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

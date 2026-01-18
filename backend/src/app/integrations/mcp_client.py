"""MCP 客户端封装。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.settings import get_settings

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
_DANGEROUS_CHARS = re.compile(r'[;&|`$]')


@dataclass
class ToolDefinition:
    """工具定义。"""

    name: str
    description: str | None = None
    input_schema: dict | None = None


@dataclass
class ToolCallResult:
    """工具调用结果。"""

    success: bool
    output: Any = None
    error: str | None = None


@dataclass
class MCPConnection:
    """MCP 连接状态。"""

    transport: str
    endpoint: str
    tools: list[ToolDefinition] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    prefer_jsonrpc: bool = False
    connected: bool = False
    stdio_process: asyncio.subprocess.Process | None = None
    stdio_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class MCPClient:
    """MCP 客户端，支持 stdio 和 http 传输。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._connections: dict[str, MCPConnection] = {}
        self._http_client: httpx.AsyncClient | None = None

    def _ensure_http_client(self) -> httpx.AsyncClient:
        if not self._http_client:
            self._http_client = httpx.AsyncClient(
                timeout=self._settings.mcp_http_timeout_seconds
            )
        return self._http_client

    def _merge_env(self, extra: dict[str, str]) -> dict[str, str] | None:
        if not extra:
            return None
        merged = dict(os.environ)
        merged.update(extra)
        return merged

    def _parse_stdio_endpoint(self, endpoint: str) -> list[str]:
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

        return parts

    def _parse_scope(
        self, scope: dict | None
    ) -> tuple[dict[str, str], dict[str, str], bool]:
        headers: dict[str, str] = {}
        env: dict[str, str] = {}
        prefer_jsonrpc = bool(self._settings.mcp_streamable_http)
        if not scope:
            return headers, env, prefer_jsonrpc

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
        if isinstance(protocol, str) and protocol.lower() == "jsonrpc":
            prefer_jsonrpc = True

        return headers, env, prefer_jsonrpc

    def _extract_tools(self, data: dict) -> list[ToolDefinition]:
        if "error" in data:
            message = data["error"].get("message", "未知错误")
            raise RuntimeError(message)

        payload = data.get("result") if isinstance(data, dict) else None
        if payload is None:
            payload = data
        tools_data = payload.get("tools", [])
        return [
            ToolDefinition(
                name=t.get("name", ""),
                description=t.get("description"),
                input_schema=t.get("inputSchema") or t.get("input_schema"),
            )
            for t in tools_data
        ]

    def _extract_call_result(self, data: dict) -> ToolCallResult:
        if "error" in data:
            return ToolCallResult(
                success=False,
                error=data["error"].get("message", "未知错误"),
            )

        payload = data.get("result") if isinstance(data, dict) else None
        if payload is None:
            payload = data

        if payload.get("isError"):
            return ToolCallResult(
                success=False,
                error=payload.get("content", [{}])[0].get("text", "调用失败"),
            )

        content = payload.get("content", [])
        output = content[0].get("text") if content else None
        return ToolCallResult(success=True, output=output)

    async def _post_http(
        self, endpoint: str, path: str, payload: dict, headers: dict[str, str]
    ) -> dict:
        client = self._ensure_http_client()
        resp = await client.post(
            f"{endpoint.rstrip('/')}{path}",
            json=payload,
            headers=headers or None,
        )
        resp.raise_for_status()
        return resp.json()

    async def _post_jsonrpc(
        self, endpoint: str, method: str, params: dict, headers: dict[str, str]
    ) -> dict:
        client = self._ensure_http_client()
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        resp = await client.post(
            f"{endpoint.rstrip('/')}/rpc",
            json=request,
            headers=headers or None,
        )
        resp.raise_for_status()
        return resp.json()

    async def connect(
        self, extension_id: str, transport: str, endpoint: str, scope: dict | None = None
    ) -> list[ToolDefinition]:
        """连接到 MCP 服务器并获取工具列表。"""
        if not self._settings.mcp_enabled:
            logger.warning("MCP 功能未启用")
            return []

        headers, env, prefer_jsonrpc = self._parse_scope(scope)

        try:
            stdio_process = None
            if transport == "http":
                tools = await self._connect_http(endpoint, headers, prefer_jsonrpc)
            elif transport == "stdio":
                tools, stdio_process = await self._connect_stdio(endpoint, env)
            else:
                raise ValueError(f"不支持的传输类型: {transport}")

            self._connections[extension_id] = MCPConnection(
                transport=transport,
                endpoint=endpoint,
                tools=tools,
                headers=headers,
                env=env,
                prefer_jsonrpc=prefer_jsonrpc,
                connected=True,
                stdio_process=stdio_process,
            )
            return tools

        except Exception as e:
            logger.error(f"MCP 连接失败: {e}", extra={"extension_id": extension_id})
            return []

    async def _connect_http(
        self, endpoint: str, headers: dict[str, str], prefer_jsonrpc: bool
    ) -> list[ToolDefinition]:
        """通过 HTTP 连接 MCP 服务器。"""
        try:
            if prefer_jsonrpc:
                data = await self._post_jsonrpc(
                    endpoint, "tools/list", {}, headers
                )
            else:
                data = await self._post_http(endpoint, "/tools/list", {}, headers)
        except httpx.HTTPStatusError:
            if prefer_jsonrpc:
                data = await self._post_http(endpoint, "/tools/list", {}, headers)
            else:
                data = await self._post_jsonrpc(
                    endpoint, "tools/list", {}, headers
                )

        return self._extract_tools(data)

    async def _spawn_stdio_process(
        self, endpoint: str, env: dict[str, str]
    ) -> asyncio.subprocess.Process:
        parts = self._parse_stdio_endpoint(endpoint)
        return await asyncio.create_subprocess_exec(
            *parts,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._merge_env(env),
        )

    async def _request_stdio(
        self, proc: asyncio.subprocess.Process, request: dict
    ) -> dict:
        if proc.stdin is None or proc.stdout is None:
            raise RuntimeError("stdio 进程不可用")
        proc.stdin.write(json.dumps(request).encode() + b"\n")
        await proc.stdin.drain()
        line = await asyncio.wait_for(
            proc.stdout.readline(), timeout=self._settings.mcp_stdio_timeout_seconds
        )
        if not line:
            raise RuntimeError("stdio 响应为空")
        return json.loads(line.decode().strip())

    async def _close_stdio_process(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            proc.kill()

    async def _connect_stdio(
        self, endpoint: str, env: dict[str, str]
    ) -> tuple[list[ToolDefinition], asyncio.subprocess.Process]:
        """通过 stdio 连接 MCP 服务器。"""
        # 发送 tools/list 请求
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

        proc = await self._spawn_stdio_process(endpoint, env)
        try:
            response = await self._request_stdio(proc, request)
        except Exception:
            await self._close_stdio_process(proc)
            raise

        return self._extract_tools(response), proc

    async def call_tool(
        self,
        extension_id: str,
        tool_name: str,
        arguments: dict | None = None,
    ) -> ToolCallResult:
        """调用 MCP 工具。"""
        conn = self._connections.get(extension_id)
        if not conn or not conn.connected:
            return ToolCallResult(success=False, error="扩展未连接")

        try:
            if conn.transport == "http":
                return await self._call_http(
                    conn.endpoint,
                    tool_name,
                    arguments,
                    conn.headers,
                    conn.prefer_jsonrpc,
                )
            elif conn.transport == "stdio":
                return await self._call_stdio(conn, tool_name, arguments)
            else:
                return ToolCallResult(success=False, error="不支持的传输类型")

        except asyncio.TimeoutError:
            return ToolCallResult(success=False, error="工具调用超时")
        except Exception as e:
            logger.error(f"工具调用失败: {e}", extra={"tool_name": tool_name})
            return ToolCallResult(success=False, error=str(e))

    async def _call_http(
        self,
        endpoint: str,
        tool_name: str,
        arguments: dict | None,
        headers: dict[str, str],
        prefer_jsonrpc: bool,
    ) -> ToolCallResult:
        """通过 HTTP 调用工具。"""
        params = {"name": tool_name, "arguments": arguments or {}}
        try:
            if prefer_jsonrpc:
                data = await self._post_jsonrpc(
                    endpoint, "tools/call", params, headers
                )
            else:
                data = await self._post_http(
                    endpoint, "/tools/call", params, headers
                )
        except httpx.HTTPStatusError:
            if prefer_jsonrpc:
                data = await self._post_http(
                    endpoint, "/tools/call", params, headers
                )
            else:
                data = await self._post_jsonrpc(
                    endpoint, "tools/call", params, headers
                )

        return self._extract_call_result(data)

    async def _call_stdio(
        self,
        conn: MCPConnection,
        tool_name: str,
        arguments: dict | None,
    ) -> ToolCallResult:
        """通过 stdio 调用工具（优先复用连接）。"""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
        }

        proc = conn.stdio_process
        if proc is None or proc.returncode is not None:
            return await self._call_stdio_once(
                conn.endpoint, tool_name, arguments, conn.env
            )

        async with conn.stdio_lock:
            proc = conn.stdio_process
            if proc is None or proc.returncode is not None:
                return await self._call_stdio_once(
                    conn.endpoint, tool_name, arguments, conn.env
                )
            try:
                response = await self._request_stdio(proc, request)
            except Exception:
                await self._close_stdio_process(proc)
                conn.stdio_process = None
                return await self._call_stdio_once(
                    conn.endpoint, tool_name, arguments, conn.env
                )

        return self._extract_call_result(response)

    async def _call_stdio_once(
        self,
        endpoint: str,
        tool_name: str,
        arguments: dict | None,
        env: dict[str, str],
    ) -> ToolCallResult:
        """通过 stdio 单次调用工具（失败时兜底）。"""
        try:
            proc = await self._spawn_stdio_process(endpoint, env)
        except ValueError as exc:
            return ToolCallResult(success=False, error=str(exc))

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
        }

        try:
            response = await self._request_stdio(proc, request)
        except Exception as exc:
            await self._close_stdio_process(proc)
            return ToolCallResult(success=False, error=str(exc))

        await self._close_stdio_process(proc)
        return self._extract_call_result(response)

    async def disconnect(self, extension_id: str) -> None:
        """断开连接。"""
        conn = self._connections.get(extension_id)
        if not conn:
            return
        if conn.transport == "stdio" and conn.stdio_process is not None:
            await self._close_stdio_process(conn.stdio_process)
        del self._connections[extension_id]

    async def close(self) -> None:
        """关闭客户端。"""
        for conn in self._connections.values():
            if conn.transport == "stdio" and conn.stdio_process is not None:
                await self._close_stdio_process(conn.stdio_process)
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._connections.clear()

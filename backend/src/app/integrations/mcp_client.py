"""MCP 客户端封装。"""

from __future__ import annotations

import asyncio
import json
import os
import re
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
            if transport == "http":
                tools = await self._connect_http(endpoint, headers, prefer_jsonrpc)
            elif transport == "stdio":
                tools = await self._connect_stdio(endpoint, env)
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

    async def _connect_stdio(self, endpoint: str, env: dict[str, str]) -> list[ToolDefinition]:
        """通过 stdio 连接 MCP 服务器。"""
        # 解析命令
        parts = endpoint.split()
        if not parts:
            raise ValueError("无效的 stdio 端点")

        # 安全验证：检查命令白名单和危险字符
        cmd = parts[0].split("/")[-1].split("\\")[-1]  # 提取命令名
        if cmd not in _ALLOWED_MCP_COMMANDS:
            raise ValueError(f"不允许的 MCP 命令: {cmd}")
        if _DANGEROUS_CHARS.search(endpoint):
            raise ValueError("端点包含危险字符")

        # 发送 tools/list 请求
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

        proc = await asyncio.create_subprocess_exec(
            *parts,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._merge_env(env),
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(json.dumps(request).encode() + b"\n"),
            timeout=self._settings.mcp_stdio_timeout_seconds,
        )

        if proc.returncode != 0:
            raise RuntimeError(f"stdio 进程失败: {stderr.decode()}")

        # 解析响应
        response = json.loads(stdout.decode().strip())
        return self._extract_tools(response)

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
                return await self._call_stdio(
                    conn.endpoint,
                    tool_name,
                    arguments,
                    conn.env,
                )
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
        endpoint: str,
        tool_name: str,
        arguments: dict | None,
        env: dict[str, str],
    ) -> ToolCallResult:
        """通过 stdio 调用工具。"""
        parts = endpoint.split()

        # 安全验证：检查命令白名单和危险字符
        cmd = parts[0].split("/")[-1].split("\\")[-1]
        if cmd not in _ALLOWED_MCP_COMMANDS:
            return ToolCallResult(success=False, error=f"不允许的 MCP 命令: {cmd}")
        if _DANGEROUS_CHARS.search(endpoint):
            return ToolCallResult(success=False, error="端点包含危险字符")

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
        }

        proc = await asyncio.create_subprocess_exec(
            *parts,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._merge_env(env),
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(json.dumps(request).encode() + b"\n"),
            timeout=self._settings.mcp_stdio_timeout_seconds,
        )

        if proc.returncode != 0:
            return ToolCallResult(success=False, error=stderr.decode())

        response = json.loads(stdout.decode().strip())
        return self._extract_call_result(response)

    async def disconnect(self, extension_id: str) -> None:
        """断开连接。"""
        if extension_id in self._connections:
            del self._connections[extension_id]

    async def close(self) -> None:
        """关闭客户端。"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._connections.clear()

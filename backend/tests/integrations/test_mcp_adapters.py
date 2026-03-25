from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent

import app.integrations.mcp_adapters as mcp_adapters_module
from app.models.tool_extension import ExtensionStatus, ExtensionTransport, ToolExtension


def _build_settings() -> SimpleNamespace:
    return SimpleNamespace(
        mcp_enabled=True,
        mcp_http_timeout_seconds=30,
        mcp_stdio_timeout_seconds=30,
    )


def _build_stdio_extension() -> ToolExtension:
    return ToolExtension(
        id=uuid.UUID("00000000-0000-0000-0000-000000000301"),
        name="Sequential Thinking",
        transport=ExtensionTransport.STDIO,
        status=ExtensionStatus.ENABLED,
        http_config=None,
        stdio_config={
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
            "env": {"FOO": "bar"},
            "cwd": "C:\\Tools\\mcp",
            "timeout_seconds": 45,
        },
        observability_config=None,
    )


def test_build_mcp_server_params_accepts_direct_stdio_command_config() -> None:
    ext = _build_stdio_extension()

    params = mcp_adapters_module.build_mcp_server_params(ext, _build_settings())

    assert params == {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "env": {"FOO": "bar"},
        "cwd": "C:\\Tools\\mcp",
    }


@pytest.mark.asyncio
async def test_open_mcp_tool_runtime_uses_explicit_sessions_instead_of_stateless_get_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ext = ToolExtension(
        id=uuid.UUID("00000000-0000-0000-0000-000000000302"),
        name="LangChain Docs",
        transport=ExtensionTransport.HTTP,
        status=ExtensionStatus.ENABLED,
        http_config={
            "url": "https://docs.langchain.com/mcp",
            "protocol": "streamable_http",
            "headers": {},
            "auth": {"type": "none"},
        },
        stdio_config=None,
        observability_config=None,
    )
    settings = _build_settings()
    entered: list[str] = []
    exited: list[str] = []
    session_by_server: dict[str, object] = {}

    class _FakeClient:
        def __init__(
            self,
            connections: dict[str, dict[str, object]],
            *,
            callbacks: object | None = None,
            tool_interceptors: list[object] | None = None,
            tool_name_prefix: bool = False,
        ) -> None:
            self.connections = connections
            self.callbacks = callbacks
            self.tool_interceptors = tool_interceptors or []
            self.tool_name_prefix = tool_name_prefix

        def session(self, server_name: str, *, auto_initialize: bool = True):
            assert auto_initialize is True

            @asynccontextmanager
            async def _ctx():
                entered.append(server_name)
                session = object()
                session_by_server[server_name] = session
                try:
                    yield session
                finally:
                    exited.append(server_name)

            return _ctx()

        async def get_tools(self, *, server_name: str | None = None):
            raise AssertionError("must not use stateless get_tools() in runtime path")

    async def _fake_load_mcp_tools(
        session: object,
        *,
        callbacks: object | None = None,
        tool_interceptors: list[object] | None = None,
        server_name: str | None = None,
        tool_name_prefix: bool = False,
    ) -> list[object]:
        assert server_name is not None
        assert session is session_by_server[server_name]
        assert tool_name_prefix is False
        assert tool_interceptors
        return [SimpleNamespace(name="search_docs_by_lang_chain", description="LangChain MCP docs")]

    monkeypatch.setattr(mcp_adapters_module, "MultiServerMCPClient", _FakeClient)
    monkeypatch.setattr(mcp_adapters_module, "load_langchain_mcp_tools", _fake_load_mcp_tools)

    async with mcp_adapters_module.open_mcp_tool_runtime(
        settings=settings,
        extensions=[ext],
        allow_external=True,
    ) as (entries, diagnostics):
        assert [entry.raw_tool_name for entry in entries] == ["search_docs_by_lang_chain"]
        assert diagnostics[str(ext.id)].status == "ok"
        assert entered == [str(ext.id)]
        assert exited == []

    assert exited == [str(ext.id)]


@pytest.mark.asyncio
async def test_mcp_tool_call_audit_interceptor_does_not_use_reserved_logrecord_keys() -> None:
    ext = ToolExtension(
        id=uuid.UUID("00000000-0000-0000-0000-000000000303"),
        name="LangChain Docs",
        transport=ExtensionTransport.HTTP,
        status=ExtensionStatus.ENABLED,
        http_config={
            "url": "https://docs.langchain.com/mcp",
            "protocol": "streamable_http",
            "headers": {},
            "auth": {"type": "none"},
        },
        stdio_config=None,
        observability_config=None,
    )
    interceptor = mcp_adapters_module.McpToolCallAuditInterceptor(
        settings=_build_settings(),
        allow_external=True,
        extensions_by_id={str(ext.id): ext},
    )
    request = SimpleNamespace(
        server_name=str(ext.id),
        name="search_docs_by_lang_chain",
        args={"query": "mcp python"},
    )

    async def _handler(_request: object) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text="ok")],
            isError=False,
        )

    previous_level = mcp_adapters_module.logger.level
    mcp_adapters_module.logger.setLevel("INFO")
    try:
        result = await interceptor(request, _handler)
    finally:
        mcp_adapters_module.logger.setLevel(previous_level)

    assert isinstance(result, CallToolResult)
    assert result.isError is False
    assert result.content[0].text == "ok"

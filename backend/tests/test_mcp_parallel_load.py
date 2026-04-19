from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
import uuid

import pytest

from app.models.tool_extension import ExtensionTransport
from app.integrations import mcp_adapters as adapters


def _make_extension(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        transport=ExtensionTransport.HTTP,
        http_config={"url": f"https://{name}.example.com", "protocol": "streamable_http"},
        stdio_config=None,
    )


def _make_settings() -> SimpleNamespace:
    return SimpleNamespace(
        mcp_enabled=True,
        mcp_http_timeout_seconds=30,
        mcp_stdio_timeout_seconds=10,
        mcp_parallel_load_enabled=True,
    )


@pytest.mark.asyncio
async def test_load_mcp_tools_with_diagnostics_loads_extensions_in_parallel(
    monkeypatch,
) -> None:
    state = {"active": 0, "max_active": 0}

    class _FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        async def get_tools(self, *, server_name: str):
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            await asyncio.sleep(0.05)
            state["active"] -= 1
            return [SimpleNamespace(name=f"{server_name}_tool")]

    monkeypatch.setattr(adapters, "MultiServerMCPClient", _FakeClient)

    extensions = [_make_extension("alpha"), _make_extension("beta")]
    entries, diagnostics = await adapters.load_mcp_tools_with_diagnostics(
        settings=_make_settings(),
        extensions=extensions,
    )

    assert state["max_active"] == 2
    assert [entry.extension.name for entry in entries] == ["alpha", "beta"]
    assert all(diagnostics[str(ext.id)].status == "ok" for ext in extensions)


@pytest.mark.asyncio
async def test_open_mcp_tool_runtime_opens_sessions_in_parallel(monkeypatch) -> None:
    state = {"active": 0, "max_active": 0, "closed": []}

    class _SessionContext(AbstractAsyncContextManager):
        def __init__(self, server_name: str) -> None:
            self.server_name = server_name

        async def __aenter__(self) -> SimpleNamespace:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            await asyncio.sleep(0.05)
            state["active"] -= 1
            return SimpleNamespace(server_name=self.server_name)

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            state["closed"].append(self.server_name)
            return False

    class _FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            self.callbacks = []
            self.tool_interceptors = []
            self.tool_name_prefix = False

        def session(self, server_name: str) -> _SessionContext:
            return _SessionContext(server_name)

    async def _fake_load_langchain_mcp_tools(
        session,
        *,
        callbacks,
        tool_interceptors,
        server_name: str,
        tool_name_prefix: bool,
    ):
        assert callbacks == []
        assert tool_interceptors == []
        assert tool_name_prefix is False
        return [SimpleNamespace(name=f"{server_name}_tool", session=session.server_name)]

    monkeypatch.setattr(adapters, "MultiServerMCPClient", _FakeClient)
    monkeypatch.setattr(adapters, "load_langchain_mcp_tools", _fake_load_langchain_mcp_tools)

    extensions = [_make_extension("alpha"), _make_extension("beta")]
    async with adapters.open_mcp_tool_runtime(
        settings=_make_settings(),
        extensions=extensions,
    ) as (entries, diagnostics):
        assert state["max_active"] == 2
        assert [entry.extension.name for entry in entries] == ["alpha", "beta"]
        assert all(diagnostics[str(ext.id)].status == "ok" for ext in extensions)

    assert sorted(state["closed"]) == sorted(str(ext.id) for ext in extensions)

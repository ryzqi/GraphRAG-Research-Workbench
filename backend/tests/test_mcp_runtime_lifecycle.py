from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.integrations import mcp_adapters


@pytest.mark.asyncio
async def test_open_mcp_tool_runtime_keeps_session_enter_and_exit_on_same_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_records: dict[str, dict[str, asyncio.Task[object] | None]] = {}

    class FakeSessionContext:
        def __init__(self, server_name: str) -> None:
            self._server_name = server_name

        async def __aenter__(self) -> object:
            task_records.setdefault(self._server_name, {})["enter"] = (
                asyncio.current_task()
            )
            return object()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            task_records.setdefault(self._server_name, {})["exit"] = (
                asyncio.current_task()
            )

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            self.callbacks = object()
            self.tool_interceptors = []
            self.tool_name_prefix = False

        def session(self, server_name: str) -> FakeSessionContext:
            return FakeSessionContext(server_name)

    async def fake_load_langchain_mcp_tools(*_args, **_kwargs) -> list[object]:
        return [SimpleNamespace(name="fake-tool")]

    monkeypatch.setattr(
        mcp_adapters,
        "build_mcp_connections",
        lambda _extensions, _settings: {"ext-1": object()},
    )
    monkeypatch.setattr(
        mcp_adapters,
        "_build_tool_interceptors",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(mcp_adapters, "MultiServerMCPClient", FakeClient)
    monkeypatch.setattr(
        mcp_adapters,
        "load_langchain_mcp_tools",
        fake_load_langchain_mcp_tools,
    )

    settings = SimpleNamespace(
        mcp_enabled=True,
        mcp_parallel_load_enabled=True,
    )
    extension = SimpleNamespace(id="ext-1")

    async with mcp_adapters.open_mcp_tool_runtime(
        settings=settings,
        extensions=[extension],
        allow_external=True,
    ) as (entries, diagnostics):
        assert [entry.raw_tool_name for entry in entries] == ["fake-tool"]
        assert diagnostics["ext-1"].status == "ok"

    assert task_records["ext-1"]["enter"] is task_records["ext-1"]["exit"]

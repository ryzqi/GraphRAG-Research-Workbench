from __future__ import annotations

import uuid

import pytest
from langchain.tools import tool as lc_tool

import app.agents.tool_calling.registry as registry
from app.agents.tool_calling.registry import build_tool_registry
from app.agents.tool_calling.utils import make_mcp_tool_name
from app.core.settings import Settings
from app.integrations.mcp_adapters import McpToolEntry
from app.models.tool_extension import ExtensionStatus, ExtensionTransport, ToolExtension


@pytest.mark.asyncio
async def test_build_tool_registry_mcp_namespacing(monkeypatch: pytest.MonkeyPatch) -> None:
    ext = ToolExtension(
        id=uuid.uuid4(),
        name="demo_ext",
        transport=ExtensionTransport.HTTP,
        endpoint="http://localhost:8000/mcp",
        status=ExtensionStatus.ENABLED,
        scope=None,
    )

    @lc_tool("search", description="demo")
    async def _demo_tool(query: str) -> str:
        return query

    async def _fake_load_mcp_tools(*, settings, extensions):
        return [McpToolEntry(extension=ext, tool=_demo_tool, raw_tool_name="search")]

    monkeypatch.setattr(registry, "load_mcp_tools", _fake_load_mcp_tools)

    settings = Settings(mcp_enabled=True)
    tools, meta_by_name = await build_tool_registry(
        settings=settings,
        extensions=[ext],
        extra_tools=[],
        include_web_search=False,
        include_mcp=True,
    )

    assert len(tools) == 1
    expected_name = make_mcp_tool_name(str(ext.id), "search")
    assert tools[0].name == expected_name
    meta = meta_by_name[expected_name]
    assert meta.raw_tool_name == "search"
    assert meta.extension_id == str(ext.id)
    assert meta.is_external is True

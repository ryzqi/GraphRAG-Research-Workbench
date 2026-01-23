from __future__ import annotations

import uuid

from langchain.tools import tool as lc_tool
from pydantic import BaseModel, Field

from app.core.settings import Settings
from app.integrations.mcp_adapters import build_mcp_server_params, tool_input_schema
from app.models.tool_extension import ExtensionStatus, ExtensionTransport, ToolExtension


def _build_extension(**kwargs) -> ToolExtension:
    base = {
        "id": uuid.uuid4(),
        "name": "demo_ext",
        "transport": ExtensionTransport.HTTP,
        "endpoint": "http://localhost:8000/mcp",
        "status": ExtensionStatus.ENABLED,
        "scope": None,
    }
    base.update(kwargs)
    return ToolExtension(**base)


def test_build_mcp_server_params_stdio_parses_command_and_env() -> None:
    settings = Settings()
    ext = _build_extension(
        transport=ExtensionTransport.STDIO,
        endpoint="python -m mcp_demo --flag",
        scope={"env": {"DEMO_KEY": "VALUE"}},
    )
    params = build_mcp_server_params(ext, settings)
    assert params["transport"] == "stdio"
    assert params["command"] == "python"
    assert params["args"] == ["-m", "mcp_demo", "--flag"]
    assert params["env"]["DEMO_KEY"] == "VALUE"


def test_build_mcp_server_params_http_merges_headers_and_auth() -> None:
    settings = Settings(mcp_streamable_http=True)
    ext = _build_extension(
        transport=ExtensionTransport.HTTP,
        scope={
            "headers": {"X-Demo": "1"},
            "auth": {"type": "bearer", "token": "abc"},
        },
    )
    params = build_mcp_server_params(ext, settings)
    assert params["transport"] == "streamable_http"
    assert params["headers"]["X-Demo"] == "1"
    assert params["headers"]["Authorization"] == "Bearer abc"


def test_tool_input_schema_from_args_schema() -> None:
    class DemoArgs(BaseModel):
        query: str = Field(..., description="查询内容")

    @lc_tool("demo_tool", description="demo", args_schema=DemoArgs)
    async def _demo_tool(query: str) -> str:
        return query

    schema = tool_input_schema(_demo_tool)
    assert schema is not None
    assert schema["properties"]["query"]["type"] == "string"

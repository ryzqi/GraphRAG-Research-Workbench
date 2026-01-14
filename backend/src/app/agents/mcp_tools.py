"""MCP 工具适配为 LangChain Tool。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from app.integrations.mcp_client import MCPClient, ToolDefinition
from app.models.tool_extension import ToolExtension


def _normalize_model_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    return f"McpTool_{cleaned}" if cleaned else "McpTool"


def _json_type_to_py(schema_type: object) -> type:
    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list[object]
    if schema_type == "object":
        return dict[str, object]
    return object


def _build_args_schema(tool: ToolDefinition) -> type[BaseModel] | None:
    schema = tool.input_schema or {}
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None

    required = schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()

    fields: dict[str, tuple[type, Field]] = {}
    for name, prop in properties.items():
        if not isinstance(prop, dict):
            continue
        is_required = name in required_names
        field_type = _json_type_to_py(prop.get("type"))
        annotated_type = field_type if is_required else field_type | None
        default = ... if is_required else None
        description = prop.get("description") if isinstance(prop.get("description"), str) else None
        fields[name] = (annotated_type, Field(default=default, description=description))

    if not fields:
        return None

    return create_model(_normalize_model_name(tool.name), **fields)


def _stringify_output(output: object) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return json.dumps(output, ensure_ascii=False)


@dataclass(frozen=True)
class McpToolAdapter:
    """将 MCP 工具包装为 LangChain Tool。"""

    mcp: MCPClient
    extension_id: str
    tool: ToolDefinition

    def to_langchain_tool(self) -> BaseTool:
        args_schema = _build_args_schema(self.tool)
        description = self.tool.description or "MCP 工具"

        async def _call_tool(**kwargs: object) -> str:
            result = await self.mcp.call_tool(
                self.extension_id, self.tool.name, kwargs
            )
            if result.success:
                return _stringify_output(result.output)
            raise RuntimeError(result.error or "MCP 工具调用失败")

        return StructuredTool.from_function(
            name=self.tool.name,
            description=description,
            args_schema=args_schema,
            coroutine=_call_tool,
        )


async def build_mcp_tools(
    mcp: MCPClient, extensions: Iterable[ToolExtension]
) -> list[BaseTool]:
    tools: list[BaseTool] = []
    for ext in extensions:
        tool_defs = await mcp.connect(
            str(ext.id), ext.transport.value, ext.endpoint, ext.scope
        )
        for tool_def in tool_defs:
            tools.append(
                McpToolAdapter(
                    mcp=mcp,
                    extension_id=str(ext.id),
                    tool=tool_def,
                ).to_langchain_tool()
            )
    return tools

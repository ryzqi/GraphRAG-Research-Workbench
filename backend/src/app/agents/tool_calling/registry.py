"""统一工具注册与命名空间。

目标：把内置工具、kb_retrieve、研究工具与 MCP 扩展工具统一为 LangChain Tools，
并在需要时提供 tool_name -> 元信息 的映射，便于审批展示与审计落库。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Sequence

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from app.agents.tools.web_search import build_web_search_tool
from app.core.settings import Settings
from app.integrations.mcp_client import MCPClient, ToolDefinition
from app.models.tool_extension import ToolExtension

from .utils import DEFAULT_TOOL_OUTPUT_MAX_CHARS, make_mcp_tool_name, truncate_tool_output


@dataclass(frozen=True, slots=True)
class ToolMeta:
    """工具元信息（供审批展示/审计映射）。"""

    tool_name: str
    raw_tool_name: str
    extension_id: str
    extension_name: str | None
    is_builtin: bool
    is_external: bool


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
    try:
        return json.dumps(output, ensure_ascii=False)
    except TypeError:
        return str(output)



async def build_tool_registry(
    *,
    settings: Settings,
    mcp: MCPClient | None = None,
    extensions: Sequence[ToolExtension] | None = None,
    extra_tools: Sequence[BaseTool] | None = None,
    include_web_search: bool = True,
    include_mcp: bool = True,
    tool_output_max_chars: int = DEFAULT_TOOL_OUTPUT_MAX_CHARS,
) -> tuple[list[BaseTool], dict[str, ToolMeta]]:
    """构建工具列表与 tool_name -> ToolMeta 映射。"""

    tools: list[BaseTool] = []
    meta_by_name: dict[str, ToolMeta] = {}

    def _add_tool(tool: BaseTool, meta: ToolMeta) -> None:
        if tool.name in meta_by_name:
            raise ValueError(f"工具名冲突: {tool.name}")
        tools.append(tool)
        meta_by_name[tool.name] = meta

    # 先注册内部/业务工具（不需要命名空间）
    for tool in extra_tools or []:
        _add_tool(
            tool,
            ToolMeta(
                tool_name=tool.name,
                raw_tool_name=tool.name,
                extension_id="builtin",
                extension_name="内置工具",
                is_builtin=True,
                is_external=False,
            ),
        )

    # Web 搜索（外部工具）
    if include_web_search and settings.web_search_api_key:
        base_tool = build_web_search_tool(settings)

        async def _call_web_search(**kwargs: object) -> str:
            output = await base_tool.ainvoke(kwargs)
            text, _ = truncate_tool_output(str(output), tool_output_max_chars)
            return text

        web_tool = StructuredTool.from_function(
            name=base_tool.name,
            description=base_tool.description,
            args_schema=getattr(base_tool, "args_schema", None),
            coroutine=_call_web_search,
        )
        _add_tool(
            web_tool,
            ToolMeta(
                tool_name=web_tool.name,
                raw_tool_name=web_tool.name,
                extension_id="builtin",
                extension_name="内置工具",
                is_builtin=True,
                is_external=True,
            ),
        )

    # MCP 扩展工具（外部工具，需命名空间）
    if include_mcp and mcp is not None and settings.mcp_enabled and extensions:
        for ext in extensions:
            tool_defs = await mcp.connect(
                str(ext.id), ext.transport.value, ext.endpoint, ext.scope
            )
            for tool_def in tool_defs:
                tool_name = make_mcp_tool_name(str(ext.id), tool_def.name)
                args_schema = _build_args_schema(tool_def)
                description = tool_def.description or "MCP 工具"

                async def _call_mcp_tool(
                    _extension_id: str = str(ext.id),
                    _raw_tool_name: str = tool_def.name,
                    **kwargs: object,
                ) -> str:
                    result = await mcp.call_tool(_extension_id, _raw_tool_name, kwargs)
                    if result.success:
                        text = _stringify_output(result.output)
                        text, _ = truncate_tool_output(text, tool_output_max_chars)
                        return text
                    err = result.error or "MCP 工具调用失败"
                    err, _ = truncate_tool_output(str(err), tool_output_max_chars)
                    raise RuntimeError(err)

                tool = StructuredTool.from_function(
                    name=tool_name,
                    description=description,
                    args_schema=args_schema,
                    coroutine=_call_mcp_tool,
                )
                _add_tool(
                    tool,
                    ToolMeta(
                        tool_name=tool_name,
                        raw_tool_name=tool_def.name,
                        extension_id=str(ext.id),
                        extension_name=ext.name,
                        is_builtin=False,
                        is_external=True,
                    ),
                )

    return tools, meta_by_name

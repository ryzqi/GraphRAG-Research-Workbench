"""统一工具注册与命名空间。

目标：把内置工具、kb_retrieve、研究工具与 MCP 扩展工具统一为 LangChain Tools，
并在需要时提供 tool_name -> 元信息 的映射，便于审批展示与审计落库。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

from langchain.tools import BaseTool, tool as lc_tool

from app.agents.tools.web_search import (
    build_web_crawl_tool,
    build_web_extract_tool,
    build_web_research_tool,
    build_web_search_tool,
)
from app.core.settings import Settings
from app.integrations.mcp_adapters import load_mcp_tools
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
    extensions: Sequence[ToolExtension] | None = None,
    extra_tools: Sequence[BaseTool] | None = None,
    include_web_search: bool = True,
    include_web_extract: bool = False,
    include_web_crawl: bool = False,
    include_web_research: bool = False,
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

    def _wrap_external_tool(base_tool: BaseTool) -> None:
        async def _call_external(**kwargs: object) -> str:
            output = await base_tool.ainvoke(kwargs)
            text, _ = truncate_tool_output(str(output), tool_output_max_chars)
            return text

        tool = lc_tool(
            base_tool.name,
            description=base_tool.description,
            args_schema=getattr(base_tool, "args_schema", None),
        )(_call_external)
        _add_tool(
            tool,
            ToolMeta(
                tool_name=tool.name,
                raw_tool_name=tool.name,
                extension_id="builtin",
                extension_name="内置工具",
                is_builtin=True,
                is_external=True,
            ),
        )

    # Tavily 外部工具
    if settings.web_search_api_key:
        if include_web_search:
            _wrap_external_tool(build_web_search_tool(settings))
        if include_web_extract:
            _wrap_external_tool(build_web_extract_tool(settings))
        if include_web_crawl:
            _wrap_external_tool(build_web_crawl_tool(settings))
        if include_web_research:
            _wrap_external_tool(build_web_research_tool(settings))

    # MCP 扩展工具（外部工具，需命名空间）
    if include_mcp and settings.mcp_enabled and extensions:
        mcp_entries = await load_mcp_tools(settings=settings, extensions=extensions)
        for entry in mcp_entries:
            ext = entry.extension
            raw_tool_name = entry.raw_tool_name
            base_tool = entry.tool
            tool_name = make_mcp_tool_name(str(ext.id), raw_tool_name)
            description = getattr(base_tool, "description", None) or "MCP 工具"
            args_schema = getattr(base_tool, "args_schema", None)

            async def _call_mcp_tool(
                _tool: BaseTool = base_tool,
                **kwargs: object,
            ) -> str:
                try:
                    output = await _tool.ainvoke(kwargs)
                except Exception as exc:
                    err, _ = truncate_tool_output(str(exc), tool_output_max_chars)
                    raise RuntimeError(err) from exc
                text = _stringify_output(output)
                text, _ = truncate_tool_output(text, tool_output_max_chars)
                return text

            tool = lc_tool(
                tool_name,
                description=description,
                args_schema=args_schema,
            )(_call_mcp_tool)
            _add_tool(
                tool,
                ToolMeta(
                    tool_name=tool_name,
                    raw_tool_name=raw_tool_name,
                    extension_id=str(ext.id),
                    extension_name=ext.name,
                    is_builtin=False,
                    is_external=True,
                ),
            )

    return tools, meta_by_name

"""统一工具注册与命名空间。

目标：把内置工具、kb_retrieve、研究工具与 MCP 扩展工具统一为 LangChain Tools，
并在需要时提供 tool_name -> 元信息 的映射，便于审批展示与审计落库。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Sequence

import httpx
from langchain.tools import BaseTool, tool as lc_tool

from app.agents.tools.web_search import (
    build_jina_read_tool,
    has_jina_read_provider,
    has_web_extract_provider,
    has_web_search_provider,
    build_web_crawl_tool,
    build_web_extract_tool,
    build_web_research_tool,
    build_web_search_tool,
)
from app.core.settings import Settings
from app.integrations.mcp_adapters import McpToolEntry, load_mcp_tools
from app.integrations.redis_client import RedisClient
from app.models.tool_extension import ToolExtension

from .utils import DEFAULT_TOOL_OUTPUT_MAX_CHARS, make_mcp_tool_name, truncate_tool_output
from .web_tool_payloads import compact_builtin_external_output


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

def _sanitize_mcp_content(content: object) -> object:
    """将 MCP 工具输出清洗为适合 ToolMessage 的安全可序列化内容。

    - 删除 image / file 块中的大体积 base64 数据。
    - 可转换时优先把 pydantic 对象转成 dict。
    """
    if hasattr(content, "model_dump"):
        try:
            return content.model_dump()
        except Exception:
            return str(content)
    if not isinstance(content, list):
        return content
    sanitized: list[object] = []
    for item in content:
        if isinstance(item, dict):
            block = dict(item)
            if block.get("type") in {"image", "file"}:
                if "base64" in block:
                    block["base64"] = "***OMITTED***"
                if "data" in block:
                    block["data"] = "***OMITTED***"
            sanitized.append(block)
        else:
            sanitized.append(item)
    return sanitized



async def build_tool_registry(
    *,
    settings: Settings,
    extensions: Sequence[ToolExtension] | None = None,
    mcp_entries: Sequence[McpToolEntry] | None = None,
    extra_tools: Sequence[BaseTool] | None = None,
    include_web_search: bool = True,
    include_web_extract: bool = False,
    include_web_crawl: bool = False,
    include_web_research: bool = False,
    include_mcp: bool = True,
    tool_output_max_chars: int = DEFAULT_TOOL_OUTPUT_MAX_CHARS,
    redis: RedisClient | None = None,
    http_client: httpx.AsyncClient | None = None,
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
            return compact_builtin_external_output(
                base_tool.name,
                output,
                tool_output_max_chars,
            )

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

    # 内置联网工具
    if include_web_search and has_web_search_provider(settings):
        _wrap_external_tool(
            build_web_search_tool(
                settings, redis=redis, http_client=http_client
            )
        )
    if include_web_extract and has_web_extract_provider(settings):
        _wrap_external_tool(
            build_web_extract_tool(
                settings, redis=redis, http_client=http_client
            )
        )
    if has_jina_read_provider(settings):
        _wrap_external_tool(
            build_jina_read_tool(
                settings,
                http_client=http_client,
            )
        )
    if settings.web_search_api_key:
        if include_web_crawl:
            _wrap_external_tool(
                build_web_crawl_tool(
                    settings, redis=redis, http_client=http_client
                )
            )
        if include_web_research:
            _wrap_external_tool(
                build_web_research_tool(
                    settings, redis=redis, http_client=http_client
                )
            )

    # MCP 扩展工具（外部工具，需要命名空间）
    if include_mcp and settings.mcp_enabled and extensions:
        resolved_mcp_entries = (
            list(mcp_entries)
            if mcp_entries is not None
            else await load_mcp_tools(settings=settings, extensions=extensions)
        )
        for entry in resolved_mcp_entries:
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
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    err, _ = truncate_tool_output(str(exc), tool_output_max_chars)
                    payload = {"ok": False, "error": err}
                    text, _ = truncate_tool_output(
                        _stringify_output(payload), tool_output_max_chars
                    )
                    return text

                content: object = output
                artifact: object | None = None
                if isinstance(output, tuple) and len(output) == 2:
                    content, artifact = output

                payload: dict[str, object] = {
                    "ok": True,
                    "content": _sanitize_mcp_content(content),
                }
                if artifact is not None:
                    payload["artifact"] = artifact

                text, _ = truncate_tool_output(
                    _stringify_output(payload), tool_output_max_chars
                )
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

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langchain.tools import BaseTool

from app.agents.tool_calling.registry import ToolMeta, build_research_tool_registry
from app.core.settings import Settings
from app.integrations.mcp_adapters import McpToolEntry
from app.integrations.redis_client import RedisClient
from app.models.tool_extension import ToolExtension
from app.schemas.research import ResearchSourceTarget
from app.services.research_runtime_types import (
    DEFAULT_RESEARCH_BACKEND_POLICY,
    ResearchBackendPolicy,
    ResearchRuntimeConfig,
    ResearchRuntimeContext,
    ResearchToolRegistryBundle,
)
from app.services.research_runtime_gate import (
    DEFAULT_OUTLINE_GATED_TOOL_NAMES,
    build_outline_gate_middleware,
)


@dataclass(slots=True)
class DeepResearchRuntime:
    """研究运行时句柄。"""

    agent: Any
    config: ResearchRuntimeConfig
    tools: list[BaseTool]
    tool_meta_by_name: dict[str, ToolMeta]
    tool_groups: dict[str, tuple[str, ...]]

    def make_run_config(self, *, thread_id: str) -> dict[str, Any]:
        return build_research_run_config(thread_id=thread_id)


def build_research_run_config(*, thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def build_research_backend(
    policy: ResearchBackendPolicy = DEFAULT_RESEARCH_BACKEND_POLICY,
) -> CompositeBackend:
    """构建 CompositeBackend，明确分离临时上下文与持久记忆/技能。"""

    state_backend = StateBackend()
    store_backend = StoreBackend()
    return CompositeBackend(
        default=state_backend,
        routes={
            policy.memories_root: store_backend,
            policy.skills_root: store_backend,
        },
    )


def _select_tools_by_name(
    tools: Sequence[BaseTool],
    *,
    tool_names: Sequence[str],
) -> list[BaseTool]:
    wanted = {name for name in tool_names}
    return [tool for tool in tools if tool.name in wanted]


def _build_role_specific_subagent_prompt(
    *,
    base_prompt: str,
    name: str,
    description: str,
) -> str:
    role_map = {
        "web": (
            "你是网页来源子代理。优先用网页搜索、正文读取和抽取工具补齐官方/原始网页证据。"
            " 进入任务后先读取 handoff packet，只回答当前 claim 所需的网页证据、限制与 citation 候选。"
        ),
        "paper": (
            "你是论文来源子代理。优先补齐论文、预印本与技术报告证据。"
            " 进入任务后先读取 handoff packet，只返回与当前 claim 直接相关的论文发现、限制与 citation 候选。"
        ),
        "claim-verifier": (
            "你是 claim 验证子代理。围绕单个 claim 收集支撑证据、反证、限制与开放问题。"
            " 先更新 claim-bundles，再决定是否继续搜索。"
        ),
        "section-writer": (
            "你是章节写作子代理，只消费已验证工件。"
            " 负责把 claim bundle、evidence ledger 和 section brief 扩写成可审计章节，不得越过未闭合证据直接下结论。"
        ),
        "citation": (
            "你是引用与报告子代理。"
            " 负责 citation 审计、执行摘要、关键要点、建议与 report-context 收口，确保最终报告中的结论、引用索引与限制一致。"
        ),
    }
    role_instruction = role_map.get(name)
    if not role_instruction:
        return base_prompt
    return (
        f"{base_prompt.strip()}\n\n"
        "## Subagent Role\n"
        f"- 名称：{name}\n"
        f"- 描述：{description}\n"
        f"- 角色要求：{role_instruction}\n"
        "- 每次接手任务前先读取 handoff packet（委派包），并只完成当前子任务。"
    ).strip()


def _build_source_specialized_subagents(
    *,
    config: ResearchRuntimeConfig,
    tools: Sequence[BaseTool],
    tool_groups: dict[str, tuple[str, ...]],
    resolved_skill_paths: Sequence[str],
) -> list[dict[str, Any]]:
    general_purpose_subagent: dict[str, Any] = {
        "name": config.subagent_name,
        "description": config.subagent_description,
        "system_prompt": config.system_prompt,
        "tools": list(tools),
        "model": config.subagent_model,
    }
    if resolved_skill_paths:
        general_purpose_subagent["skills"] = list(resolved_skill_paths)
    if config.interrupt_on:
        general_purpose_subagent["interrupt_on"] = dict(config.interrupt_on)

    subagents: list[dict[str, Any]] = [general_purpose_subagent]
    for name, description in (
        ("web", "网页来源子代理：负责 Tavily、Jina Reader、SearXNG 路线。"),
        ("paper", "论文来源子代理：负责 arXiv 搜索与论文基线构建。"),
        ("claim-verifier", "claim 验证子代理：围绕单个 claim 做证据收集、反证和置信度判断。"),
        ("section-writer", "章节写作子代理：只消费已验证工件，负责扩写章节简报与报告草稿。"),
    ):
        group_tools = _select_tools_by_name(tools, tool_names=tool_groups.get(name, ()))
        if not group_tools and name in {"web", "paper"}:
            continue
        subagent: dict[str, Any] = {
            "name": name,
            "description": description,
            "system_prompt": _build_role_specific_subagent_prompt(
                base_prompt=config.system_prompt,
                name=name,
                description=description,
            ),
            "model": config.subagent_model,
        }
        if group_tools:
            subagent["tools"] = group_tools
        if resolved_skill_paths:
            subagent["skills"] = list(resolved_skill_paths)
        if config.interrupt_on:
            subagent["interrupt_on"] = dict(config.interrupt_on)
        subagents.append(subagent)

    citation_subagent: dict[str, Any] = {
        "name": "citation",
        "description": "引用与报告子代理：负责 finalizer 前的 citation/report 收口。",
        "system_prompt": _build_role_specific_subagent_prompt(
            base_prompt=config.system_prompt,
            name="citation",
            description="引用与报告子代理：负责 finalizer 前的 citation/report 收口。",
        ),
        "model": config.finalizer_model,
    }
    if resolved_skill_paths:
        citation_subagent["skills"] = list(resolved_skill_paths)
    subagents.append(citation_subagent)
    return subagents


def resolve_source_subagent_route(
    target_sources: Sequence[ResearchSourceTarget],
) -> tuple[str, ...]:
    normalized = {item for item in target_sources}
    if (
        ResearchSourceTarget.WEB in normalized
        and ResearchSourceTarget.PAPER in normalized
    ):
        return ("paper", "web", "claim-verifier", "section-writer", "citation")
    if ResearchSourceTarget.PAPER in normalized:
        return ("paper", "claim-verifier", "section-writer", "citation")
    if ResearchSourceTarget.WEB in normalized:
        return ("web", "claim-verifier", "section-writer", "citation")
    return ("claim-verifier", "section-writer", "citation")


async def create_deep_research_runtime(
    *,
    settings: Settings,
    config: ResearchRuntimeConfig,
    response_format: Any | None = None,
    extensions: Sequence[ToolExtension] | None = None,
    mcp_entries: Sequence[McpToolEntry] | None = None,
    extra_tools: Sequence[BaseTool] | None = None,
    redis: RedisClient | None = None,
    http_client: Any | None = None,
    checkpointer: Any | None = None,
    store: Any | None = None,
) -> DeepResearchRuntime:
    """构建 Deep Agents research runtime。"""

    registry_bundle: ResearchToolRegistryBundle = await build_research_tool_registry(
        settings=settings,
        extra_tools=extra_tools,
        redis=redis,
        http_client=http_client,
    )
    del extensions, mcp_entries

    tools = registry_bundle.tools
    tool_meta_by_name = registry_bundle.tool_meta_by_name
    resolved_skill_paths = list(config.skill_paths)
    outline_gate_tool_names = {
        *DEFAULT_OUTLINE_GATED_TOOL_NAMES,
        *registry_bundle.tool_groups.get("web", ()),
        *registry_bundle.tool_groups.get("paper", ()),
    }

    agent_kwargs: dict[str, Any] = {
        "name": config.name,
        "model": config.primary_model,
        "tools": tools,
        "middleware": [
            build_outline_gate_middleware(
                gated_tool_names=tuple(sorted(outline_gate_tool_names))
            )
        ],
        "system_prompt": config.system_prompt,
        "subagents": _build_source_specialized_subagents(
            config=config,
            tools=tools,
            tool_groups=registry_bundle.tool_groups,
            resolved_skill_paths=resolved_skill_paths,
        ),
        "skills": resolved_skill_paths,
        "memory": list(config.memory_paths),
        "checkpointer": checkpointer,
        "store": store,
        "backend": build_research_backend(config.backend_policy),
        "context_schema": ResearchRuntimeContext,
        "interrupt_on": dict(config.interrupt_on) if config.interrupt_on else None,
    }
    if response_format is not None:
        agent_kwargs["response_format"] = response_format

    agent = create_deep_agent(**agent_kwargs)
    return DeepResearchRuntime(
        agent=agent,
        config=config,
        tools=tools,
        tool_meta_by_name=tool_meta_by_name,
        tool_groups=registry_bundle.tool_groups,
    )

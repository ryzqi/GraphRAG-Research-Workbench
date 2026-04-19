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
from app.prompts import get_prompt_loader
from app.schemas.research import ResearchSourceTarget
from app.services.research_runtime_types import (
    DEFAULT_RESEARCH_BACKEND_POLICY,
    ResearchBackendPolicy,
    ResearchRuntimeConfig,
    ResearchRuntimeContext,
    ResearchToolRegistryBundle,
)
from app.services.research_runtime_gate import (
    DEFAULT_BREADTH_GATED_TOOL_NAMES,
    build_breadth_gate_middleware,
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

_SUBAGENT_TEMPLATE_KEYS = {
    "web-researcher": "research/subagent_web",
    "paper-researcher": "research/subagent_paper",
    "claim-verifier": "research/subagent_claim_verifier",
    "section-writer": "research/subagent_section_writer",
    "citation-steward": "research/subagent_citation_steward",
    "evidence-critic": "research/subagent_evidence_critic",
    "coverage-critic": "research/subagent_coverage_critic",
}

_SUBAGENT_DESCRIPTIONS = {
    "web-researcher": "网页来源子代理：调用 web_search / jina_read / tavily 工具补证。",
    "paper-researcher": "论文来源子代理：调用 arxiv_search / arxiv_fetch 补证。",
    "claim-verifier": "claim 验证子代理：围绕单 claim 组织证据、反证与状态裁决。",
    "section-writer": "章节写作子代理：只消费已验证工件扩写章节，不调搜索工具。",
    "citation-steward": "引用收口子代理：finalize 前审计 citation 与 excerpts。",
    "evidence-critic": "证据只读批评子代理：产出 evidence-critique.json。",
    "coverage-critic": "覆盖只读批评子代理：产出 coverage-critique.json。",
}


def _subagent_tools(
    *,
    name: str,
    tools: Sequence[BaseTool],
    tool_groups: dict[str, tuple[str, ...]],
) -> list[BaseTool]:
    if name == "web-researcher":
        return _select_tools_by_name(
            tools,
            tool_names=tuple(tool_groups.get("web", ())) + ("record_runtime_activity",),
        )
    if name == "paper-researcher":
        return _select_tools_by_name(
            tools,
            tool_names=tuple(tool_groups.get("paper", ())) + ("record_runtime_activity",),
        )
    if name == "claim-verifier":
        return _select_tools_by_name(
            tools,
            tool_names=(
                *tool_groups.get("web", ()),
                *tool_groups.get("paper", ()),
                "record_runtime_activity",
            ),
        )
    if name == "section-writer":
        return _select_tools_by_name(tools, tool_names=("record_runtime_activity",))
    return []


def _assemble_research_subagents(
    *,
    config: ResearchRuntimeConfig,
    tools: Sequence[BaseTool],
    tool_groups: dict[str, tuple[str, ...]],
    resolved_skill_paths: Sequence[str],
) -> list[dict[str, Any]]:
    loader = get_prompt_loader()
    shared_contract = loader.render("research/shared_contract")
    subagents: list[dict[str, Any]] = []
    for name, template_key in _SUBAGENT_TEMPLATE_KEYS.items():
        system_prompt = loader.render(
            template_key,
            shared_contract_block=shared_contract,
        )
        model = (
            config.finalizer_model
            if name in {"citation-steward", "evidence-critic", "coverage-critic"}
            else config.subagent_model
        )
        entry: dict[str, Any] = {
            "name": name,
            "description": _SUBAGENT_DESCRIPTIONS[name],
            "system_prompt": system_prompt,
            "model": model,
        }
        subagent_tools = _subagent_tools(
            name=name,
            tools=tools,
            tool_groups=tool_groups,
        )
        if subagent_tools:
            entry["tools"] = subagent_tools
        if resolved_skill_paths:
            entry["skills"] = list(resolved_skill_paths)
        if config.interrupt_on:
            entry["interrupt_on"] = dict(config.interrupt_on)
        subagents.append(entry)
    return subagents


def resolve_source_subagent_route(
    target_sources: Sequence[ResearchSourceTarget],
) -> tuple[str, ...]:
    normalized = {item for item in target_sources}
    base: tuple[str, ...] = ("claim-verifier",)
    if ResearchSourceTarget.WEB in normalized:
        base += ("web-researcher",)
    if ResearchSourceTarget.PAPER in normalized:
        base += ("paper-researcher",)
    return base + (
        "section-writer",
        "evidence-critic",
        "coverage-critic",
        "citation-steward",
    )


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
    breadth_gate_tool_names = tuple(sorted(DEFAULT_BREADTH_GATED_TOOL_NAMES))

    agent_kwargs: dict[str, Any] = {
        "name": config.name,
        "model": config.primary_model,
        "tools": tools,
        "middleware": [
            build_breadth_gate_middleware(
                gated_tool_names=breadth_gate_tool_names
            )
        ],
        "system_prompt": config.system_prompt,
        "subagents": _assemble_research_subagents(
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

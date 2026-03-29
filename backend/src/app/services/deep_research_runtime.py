"""Deep Research runtime 单入口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langchain.tools import BaseTool

from app.agents.tool_calling.registry import (
    ToolMeta,
    build_research_tool_registry,
)
from app.core.checkpoint import CheckpointManager
from app.core.memory_store import StoreManager
from app.core.settings import Settings
from app.integrations.mcp_adapters import McpToolEntry
from app.integrations.redis_client import RedisClient
from app.models.tool_extension import ToolExtension
from app.schemas.research import ResearchSourceTarget
from app.services.research_runtime_types import (
    DEFAULT_RESEARCH_BACKEND_POLICY,
    ResearchBackendPolicy,
    ResearchRuntimeConfig,
    ResearchToolRegistryBundle,
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

    def stream_kwargs(self) -> dict[str, Any]:
        return self.config.stream_policy.as_kwargs()


def build_research_run_config(*, thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def build_research_backend_factory(
    policy: ResearchBackendPolicy = DEFAULT_RESEARCH_BACKEND_POLICY,
):
    """构建 CompositeBackend，明确分离临时上下文与持久记忆/技能。"""

    def _factory(runtime: Any) -> CompositeBackend:
        state_backend = StateBackend(runtime)
        store_backend = StoreBackend(runtime)
        return CompositeBackend(
            default=state_backend,
            routes={
                policy.workspace_root: state_backend,
                policy.scratch_root: state_backend,
                policy.plans_root: state_backend,
                policy.memories_root: store_backend,
                policy.skills_root: store_backend,
            },
        )

    return _factory


def _select_tools_by_name(
    tools: Sequence[BaseTool],
    *,
    tool_names: Sequence[str],
) -> list[BaseTool]:
    wanted = {name for name in tool_names}
    return [tool for tool in tools if tool.name in wanted]


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
    ):
        group_tools = _select_tools_by_name(tools, tool_names=tool_groups.get(name, ()))
        if not group_tools:
            continue
        subagent: dict[str, Any] = {
            "name": name,
            "description": description,
            "system_prompt": config.system_prompt,
            "tools": group_tools,
            "model": config.subagent_model,
        }
        if resolved_skill_paths:
            subagent["skills"] = list(resolved_skill_paths)
        if config.interrupt_on:
            subagent["interrupt_on"] = dict(config.interrupt_on)
        subagents.append(subagent)

    citation_subagent: dict[str, Any] = {
        "name": "citation",
        "description": "引用与报告子代理：负责 finalizer 前的 citation/report 收口。",
        "system_prompt": config.system_prompt,
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
    if ResearchSourceTarget.HYBRID in normalized or (
        ResearchSourceTarget.WEB in normalized
        and ResearchSourceTarget.PAPER in normalized
    ):
        return ("paper", "web", "citation")
    if ResearchSourceTarget.PAPER in normalized:
        return ("paper", "citation")
    if ResearchSourceTarget.WEB in normalized:
        return ("web", "citation")
    return ("citation",)


async def create_deep_research_runtime(
    *,
    settings: Settings,
    config: ResearchRuntimeConfig,
    extensions: Sequence[ToolExtension] | None = None,
    mcp_entries: Sequence[McpToolEntry] | None = None,
    extra_tools: Sequence[BaseTool] | None = None,
    redis: RedisClient | None = None,
    http_client: Any | None = None,
    checkpointer: Any | None = None,
    store: Any | None = None,
) -> DeepResearchRuntime:
    """构建 Deep Agents research runtime。

    当前仅落地单入口 harness 与固定运行策略；
    source-aware provider 细化与 finalizer 留待后续任务继续扩展。
    """

    registry_bundle: ResearchToolRegistryBundle = await build_research_tool_registry(
        settings=settings,
        extra_tools=extra_tools,
        redis=redis,
        http_client=http_client,
    )
    del extensions, mcp_entries

    tools = registry_bundle.tools
    tool_meta_by_name = registry_bundle.tool_meta_by_name

    resolved_checkpointer = (
        checkpointer if checkpointer is not None else CheckpointManager.get_checkpointer()
    )
    resolved_store = store if store is not None else StoreManager.get_store()
    resolved_skill_paths = list(config.skill_paths)

    agent = create_deep_agent(
        name=config.name,
        model=config.primary_model,
        tools=tools,
        system_prompt=config.system_prompt,
        subagents=_build_source_specialized_subagents(
            config=config,
            tools=tools,
            tool_groups=registry_bundle.tool_groups,
            resolved_skill_paths=resolved_skill_paths,
        ),
        skills=resolved_skill_paths,
        memory=list(config.memory_paths),
        checkpointer=resolved_checkpointer,
        store=resolved_store,
        backend=build_research_backend_factory(config.backend_policy),
        interrupt_on=dict(config.interrupt_on) if config.interrupt_on else None,
    )
    return DeepResearchRuntime(
        agent=agent,
        config=config,
        tools=tools,
        tool_meta_by_name=tool_meta_by_name,
        tool_groups=registry_bundle.tool_groups,
    )

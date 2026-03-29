"""Deep Research runtime 单入口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langchain.tools import BaseTool

from app.agents.tool_calling.registry import ToolMeta, build_tool_registry
from app.core.checkpoint import CheckpointManager
from app.core.memory_store import StoreManager
from app.core.settings import Settings
from app.integrations.mcp_adapters import McpToolEntry
from app.integrations.redis_client import RedisClient
from app.models.tool_extension import ToolExtension
from app.services.research_runtime_types import (
    DEFAULT_RESEARCH_BACKEND_POLICY,
    ResearchBackendPolicy,
    ResearchRuntimeConfig,
)


@dataclass(slots=True)
class DeepResearchRuntime:
    """研究运行时句柄。"""

    agent: Any
    config: ResearchRuntimeConfig
    tools: list[BaseTool]
    tool_meta_by_name: dict[str, ToolMeta]

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

    tools, tool_meta_by_name = await build_tool_registry(
        settings=settings,
        extensions=extensions,
        mcp_entries=mcp_entries,
        extra_tools=extra_tools,
        redis=redis,
        http_client=http_client,
        **config.tool_registry_kwargs,
    )

    resolved_checkpointer = (
        checkpointer if checkpointer is not None else CheckpointManager.get_checkpointer()
    )
    resolved_store = store if store is not None else StoreManager.get_store()
    resolved_skill_paths = list(config.skill_paths)

    general_purpose_subagent: dict[str, Any] = {
        "name": config.subagent_name,
        "description": config.subagent_description,
        "system_prompt": config.system_prompt,
        "tools": tools,
        "model": config.subagent_model,
    }
    if resolved_skill_paths:
        general_purpose_subagent["skills"] = resolved_skill_paths
    if config.interrupt_on:
        general_purpose_subagent["interrupt_on"] = dict(config.interrupt_on)

    agent = create_deep_agent(
        name=config.name,
        model=config.primary_model,
        tools=tools,
        system_prompt=config.system_prompt,
        subagents=[general_purpose_subagent],
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
    )

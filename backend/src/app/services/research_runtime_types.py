"""Deep Research runtime 类型与固定策略。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Mapping

from langchain.tools import BaseTool

from app.config.runtime_contract import RESEARCH_RUNTIME_BACKEND_ROOTS

if TYPE_CHECKING:
    from app.agents.tool_calling.registry import ToolMeta

@dataclass(slots=True, frozen=True)
class ResearchStreamPolicy:
    """Deep Agents 流式输出固定策略。"""

    subgraphs: bool = True
    version: str = "v2"

    def as_kwargs(self) -> dict[str, Any]:
        return {
            "subgraphs": self.subgraphs,
            "version": self.version,
        }


@dataclass(slots=True, frozen=True)
class ResearchBackendPolicy:
    """Deep Agents 文件后端分层路由。"""

    workspace_root: str = RESEARCH_RUNTIME_BACKEND_ROOTS.workspace_root
    scratch_root: str = RESEARCH_RUNTIME_BACKEND_ROOTS.scratch_root
    plans_root: str = RESEARCH_RUNTIME_BACKEND_ROOTS.plans_root
    memories_root: str = RESEARCH_RUNTIME_BACKEND_ROOTS.memories_root
    skills_root: str = RESEARCH_RUNTIME_BACKEND_ROOTS.skills_root


@dataclass(slots=True, frozen=True)
class ResearchLargeResultPolicy:
    """大结果溢写策略。"""

    spill_path_prefix: str = "/scratch/research-spill/"
    max_inline_chars: int = 6_000

DEFAULT_RESEARCH_STREAM_POLICY = ResearchStreamPolicy()
DEFAULT_RESEARCH_BACKEND_POLICY = ResearchBackendPolicy()
DEFAULT_RESEARCH_LARGE_RESULT_POLICY = ResearchLargeResultPolicy()
ResearchRuntimeActivityStatus = Literal[
    "started",
    "in_progress",
    "completed",
    "failed",
    "canceled",
]


@dataclass(slots=True, frozen=True)
class ResearchRuntimeContext:
    """DeepAgents per-run runtime context."""

    session_id: str
    thread_id: str
    trace_id: str | None
    target_sources: tuple[str, ...]
    subagent_route: tuple[str, ...]
    workspace_root: str
    scratch_root: str
    plan_complexity: str = "simple"


@dataclass(slots=True, frozen=True)
class ResearchRuntimeActivityUpdate:
    """Deep Research runtime 上报的任务级活动更新。"""

    task_id: str
    title: str
    task_kind: str
    status: ResearchRuntimeActivityStatus
    agent_name: str
    subagent_name: str | None = None
    parallel_group: str | None = None
    message: str | None = None


@dataclass(slots=True)
class ResearchRuntimeConfig:
    """Deep Research runtime 固定配置。"""

    primary_model: Any
    subagent_model: Any
    system_prompt: str
    finalizer_model: Any | None = None
    finalizer_structured_method: str = "function_calling"
    name: str = "deep-research"
    include_mcp: bool = False
    memory_paths: tuple[str, ...] = ()
    skill_paths: tuple[str, ...] = ("/skills/",)
    interrupt_on: Mapping[str, bool | dict[str, Any]] = field(default_factory=dict)
    stream_policy: ResearchStreamPolicy = DEFAULT_RESEARCH_STREAM_POLICY
    backend_policy: ResearchBackendPolicy = DEFAULT_RESEARCH_BACKEND_POLICY
    large_result_policy: ResearchLargeResultPolicy = (
        DEFAULT_RESEARCH_LARGE_RESULT_POLICY
    )
    command_execution_backend: str | None = None
    critic_revise_max_passes: int = 2

    def __post_init__(self) -> None:
        if self.finalizer_model is None:
            self.finalizer_model = self.primary_model
        if self.include_mcp:
            raise ValueError("Deep Research runtime 禁止启用 MCP 工具。")
        if not str(self.system_prompt or "").strip():
            raise ValueError("system_prompt 不能为空。")
        if self.command_execution_backend == "local_shell":
            raise ValueError("Deep Research runtime 禁止使用 LocalShellBackend。")


@dataclass(slots=True, frozen=True)
class ResearchToolRegistryBundle:
    """研究模式工具注册结果。"""

    tools: list[BaseTool]
    tool_meta_by_name: dict[str, "ToolMeta"]
    tool_groups: dict[str, tuple[str, ...]]

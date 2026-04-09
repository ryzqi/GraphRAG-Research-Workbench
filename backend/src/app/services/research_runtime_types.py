"""Deep Research runtime 类型与固定策略。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping

from langchain.tools import BaseTool

if TYPE_CHECKING:
    from app.agents.tool_calling.registry import ToolMeta


class ResearchProviderId(str, Enum):
    TAVILY = "tavily"
    JINA_READER = "jina_reader"
    SEARXNG = "searxng"
    ARXIV = "arxiv"


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

    workspace_root: str = "/workspace/"
    scratch_root: str = "/scratch/"
    plans_root: str = "/plans/"
    memories_root: str = "/memories/"
    skills_root: str = "/skills/"

    @property
    def ephemeral_roots(self) -> tuple[str, str, str]:
        return (self.workspace_root, self.scratch_root, self.plans_root)

    @property
    def persistent_roots(self) -> tuple[str, str]:
        return (self.memories_root, self.skills_root)


@dataclass(slots=True, frozen=True)
class ResearchLargeResultPolicy:
    """大结果溢写策略。"""

    spill_path_prefix: str = "/scratch/research-spill/"
    max_inline_chars: int = 6_000


DEFAULT_RESEARCH_PROVIDER_IDS = (
    ResearchProviderId.TAVILY,
    ResearchProviderId.JINA_READER,
    ResearchProviderId.SEARXNG,
    ResearchProviderId.ARXIV,
)
DEFAULT_RESEARCH_STREAM_POLICY = ResearchStreamPolicy()
DEFAULT_RESEARCH_BACKEND_POLICY = ResearchBackendPolicy()
DEFAULT_RESEARCH_LARGE_RESULT_POLICY = ResearchLargeResultPolicy()


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
    provider_ids: tuple[ResearchProviderId, ...] = DEFAULT_RESEARCH_PROVIDER_IDS
    memory_paths: tuple[str, ...] = ()
    skill_paths: tuple[str, ...] = ("/skills/",)
    interrupt_on: Mapping[str, bool | dict[str, Any]] = field(default_factory=dict)
    stream_policy: ResearchStreamPolicy = DEFAULT_RESEARCH_STREAM_POLICY
    backend_policy: ResearchBackendPolicy = DEFAULT_RESEARCH_BACKEND_POLICY
    large_result_policy: ResearchLargeResultPolicy = (
        DEFAULT_RESEARCH_LARGE_RESULT_POLICY
    )
    subagent_name: str = "general-purpose"
    subagent_description: str = "通用深度研究子代理，负责隔离多步资料搜集与综合。"
    command_execution_backend: str | None = None

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

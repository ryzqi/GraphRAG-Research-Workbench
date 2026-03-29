"""Deep Research runtime 类型与固定策略。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


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

    spill_path_prefix: str = "/workspace/runtime-spill/"
    max_inline_chars: int = 16_000


DEFAULT_RESEARCH_PROVIDER_IDS = (
    ResearchProviderId.TAVILY,
    ResearchProviderId.JINA_READER,
    ResearchProviderId.SEARXNG,
    ResearchProviderId.ARXIV,
)
DEFAULT_RESEARCH_STREAM_POLICY = ResearchStreamPolicy()
DEFAULT_RESEARCH_BACKEND_POLICY = ResearchBackendPolicy()
DEFAULT_RESEARCH_LARGE_RESULT_POLICY = ResearchLargeResultPolicy()


@dataclass(slots=True)
class ResearchRuntimeConfig:
    """Deep Research runtime 固定配置。"""

    primary_model: Any
    subagent_model: Any
    system_prompt: str
    name: str = "deep-research"
    include_mcp: bool = False
    provider_ids: tuple[ResearchProviderId, ...] = DEFAULT_RESEARCH_PROVIDER_IDS
    memory_paths: tuple[str, ...] = ("/memories/AGENTS.md",)
    skill_paths: tuple[str, ...] = ("/skills/",)
    interrupt_on: Mapping[str, bool | dict[str, Any]] = field(default_factory=dict)
    stream_policy: ResearchStreamPolicy = DEFAULT_RESEARCH_STREAM_POLICY
    backend_policy: ResearchBackendPolicy = DEFAULT_RESEARCH_BACKEND_POLICY
    large_result_policy: ResearchLargeResultPolicy = DEFAULT_RESEARCH_LARGE_RESULT_POLICY
    subagent_name: str = "general-purpose"
    subagent_description: str = "通用深度研究子代理，负责隔离多步资料搜集与综合。"
    command_execution_backend: str | None = None

    def __post_init__(self) -> None:
        if self.include_mcp:
            raise ValueError("Deep Research runtime 禁止启用 MCP 工具。")
        if not str(self.system_prompt or "").strip():
            raise ValueError("system_prompt 不能为空。")
        if self.command_execution_backend == "local_shell":
            raise ValueError("Deep Research runtime 禁止使用 LocalShellBackend。")

    @property
    def tool_registry_kwargs(self) -> dict[str, bool]:
        return {
            "include_web_search": True,
            "include_web_extract": True,
            "include_web_crawl": True,
            "include_web_research": True,
            "include_mcp": False,
        }

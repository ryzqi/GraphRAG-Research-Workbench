"""Deep Research runtime 单入口。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Any, Sequence

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from deepagents.backends.utils import create_file_data
from langchain.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import BaseModel, Field, ValidationError

from app.agents.tool_calling.registry import (
    ToolMeta,
    build_research_tool_registry,
)
from app.core.settings import Settings
from app.integrations.chat_model_factory import create_chat_model
from app.integrations.mcp_adapters import McpToolEntry
from app.integrations.redis_client import RedisClient
from app.models.research_session import ResearchSession
from app.models.tool_extension import ToolExtension
from app.prompts import get_prompt_loader
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_observability import ResearchRuntimeRunResult
from app.services.research_query_mesh import build_research_query_mesh, select_required_web_providers
from app.services.research_runtime_spill import spill_json_payload
from app.services.research_runtime_types import (
    DEFAULT_RESEARCH_BACKEND_POLICY,
    ResearchBackendPolicy,
    ResearchRuntimeConfig,
    ResearchToolRegistryBundle,
)
from app.services.research_source_bundle import ResearchSourceBundleBuilder
from app.services.research_workspace_files import (
    build_research_workspace_layout,
    build_workspace_bootstrap_artifact_path_map,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_WORKSPACE_CONTEXT_DOCS: tuple[tuple[str, Path], ...] = (
    (
        "/workspace/context/api_contract_research.md",
        _REPO_ROOT / "docs" / "api_contract_research.md",
    ),
    (
        "/workspace/context/research_design.md",
        _REPO_ROOT / "full-refactor-deep-research" / "design.md",
    ),
    (
        "/workspace/context/research_readme.md",
        _REPO_ROOT / "README.md",
    ),
)
class DeepResearchStructuredResponse(BaseModel):
    findings: list[str] = Field(min_length=2)
    citations: list[ResearchCanonicalCitation] = Field(min_length=2)


class DeepResearchCitationDraft(BaseModel):
    source_type: ResearchSourceType
    source_provider: str
    retrieval_method: str
    source_id: str
    title: str | None = None
    url: str | None = None
    origin_url: str | None = None
    arxiv_id: str | None = None
    authors: list[str] = Field(default_factory=list)
    published_at: str | None = None
    pdf_url: str | None = None
    accessed_at: str | None = None


class DeepResearchStructuredResponseDraft(BaseModel):
    findings: list[str] = Field(min_length=2)
    citations: list[DeepResearchCitationDraft] = Field(min_length=2)


def _normalize_structured_response_payload(payload: Any) -> Any:
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    if not isinstance(payload, dict):
        return payload

    normalized = dict(payload)
    raw_citations = normalized.get("citations")
    if not isinstance(raw_citations, list):
        return normalized

    normalized_citations: list[Any] = []
    for item in raw_citations:
        if not isinstance(item, dict):
            normalized_citations.append(item)
            continue

        citation = dict(item)
        if citation.get("source_type") == ResearchSourceType.WEB.value:
            origin_url = citation.get("origin_url")
            if not (isinstance(origin_url, str) and origin_url.strip()):
                fallback_origin_url = citation.get("url")
                if not (isinstance(fallback_origin_url, str) and fallback_origin_url.strip()):
                    fallback_origin_url = citation.get("source_id")
                if isinstance(fallback_origin_url, str) and fallback_origin_url.strip():
                    citation["origin_url"] = fallback_origin_url.strip()
        normalized_citations.append(citation)

    normalized["citations"] = normalized_citations
    return normalized


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


def build_research_backend(
    policy: ResearchBackendPolicy = DEFAULT_RESEARCH_BACKEND_POLICY,
) -> CompositeBackend:
    """构建 CompositeBackend，明确分离临时上下文与持久记忆/技能。"""

    state_backend = StateBackend()
    store_backend = StoreBackend()
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
    if ResearchSourceTarget.WEB in normalized and ResearchSourceTarget.PAPER in normalized:
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
    response_format: Any | None = None,
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

    resolved_checkpointer = checkpointer
    resolved_store = store
    resolved_skill_paths = list(config.skill_paths)

    agent_kwargs: dict[str, Any] = {
        "name": config.name,
        "model": config.primary_model,
        "tools": tools,
        "system_prompt": config.system_prompt,
        "subagents": _build_source_specialized_subagents(
            config=config,
            tools=tools,
            tool_groups=registry_bundle.tool_groups,
            resolved_skill_paths=resolved_skill_paths,
        ),
        "skills": resolved_skill_paths,
        "memory": list(config.memory_paths),
        "checkpointer": resolved_checkpointer,
        "store": resolved_store,
        "backend": build_research_backend(config.backend_policy),
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


def _build_workspace_context_files() -> dict[str, str]:
    files: dict[str, str] = {}
    for virtual_path, disk_path in _DEFAULT_WORKSPACE_CONTEXT_DOCS:
        if not disk_path.exists():
            continue
        files[virtual_path] = disk_path.read_text(encoding="utf-8")
    return files


def _to_file_uri(path: str) -> str:
    normalized = "/" + path.lstrip("/")
    return f"file://{normalized}"


def _format_workspace_paths_block(workspace_paths: Sequence[str]) -> str:
    return "\n".join(f"- {path}" for path in workspace_paths)


def _build_runtime_prompt(
    *,
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
    workspace_paths: Sequence[str],
) -> str:
    prompt_loader = get_prompt_loader()
    route_hint = ", ".join(resolve_source_subagent_route(plan_snapshot.target_sources))
    return prompt_loader.render_with_few_shot(
        "research/runtime_user",
        question=session.question,
        research_brief=plan_snapshot.research_brief,
        target_sources=", ".join(item.value for item in plan_snapshot.target_sources),
        route_hint=route_hint,
        workspace_paths_block=_format_workspace_paths_block(workspace_paths),
    )


def _build_runtime_request_files(
    *,
    workspace_files: dict[str, str],
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
) -> dict[str, dict[str, Any]]:
    query_mesh = build_research_query_mesh(
        question=session.question,
        plan_snapshot=plan_snapshot,
    )
    request_files = {
        path: create_file_data(content)
        for path, content in workspace_files.items()
    }
    request_files["/workspace/context/session_question.txt"] = create_file_data(session.question)
    request_files["/workspace/context/plan_snapshot.json"] = create_file_data(
        json.dumps(plan_snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2)
    )
    request_files["/workspace/context/query_mesh.json"] = create_file_data(
        json.dumps(asdict(query_mesh), ensure_ascii=False, indent=2)
    )
    return request_files


def _artifact_spill_slug_for_workspace_path(workspace_path: str) -> str:
    filename = PurePosixPath(workspace_path).name
    if filename.endswith(".md"):
        return filename[:-3]
    return filename


def _require_preloaded_session_artifacts(session: ResearchSession) -> Sequence[Any]:
    if "artifacts" not in session.__dict__:
        raise RuntimeError(
            "Deep Research runtime requires session.artifacts to be preloaded."
        )
    return session.artifacts or ()


def _build_bootstrap_workspace_file_entries(
    *,
    artifacts: Sequence[Any],
    layout: Any,
    path_by_artifact_key: dict[str, str],
    large_result_policy: Any,
) -> list[tuple[str, str]]:
    workspace_entries: list[tuple[str, str]] = []
    for artifact in artifacts:
        artifact_key = getattr(artifact, "artifact_key", None)
        workspace_path = path_by_artifact_key.get(artifact_key)
        if workspace_path is None:
            continue
        content_text = getattr(artifact, "content_text", None)
        if not isinstance(content_text, str):
            continue
        if len(content_text) <= large_result_policy.max_inline_chars:
            workspace_entries.append((workspace_path, content_text))
            continue

        spill_prefix = f"{large_result_policy.spill_path_prefix.rstrip('/')}/{layout.session_slug}"
        spill_result = spill_json_payload(
            layout=layout,
            provider="workspace-bootstrap",
            slug=_artifact_spill_slug_for_workspace_path(workspace_path),
            payload={
                "artifact_key": artifact_key,
                "workspace_path": workspace_path,
                "content_text": content_text,
            },
            summary_lines=[
                f"- spilled artifact: {artifact_key}",
                f"- workspace path: {workspace_path}",
                f"- original size chars: {len(content_text)}",
            ],
            path_prefix=spill_prefix,
        )
        workspace_entries.extend(
            [
                (
                    workspace_path,
                    "\n".join(
                        [
                            "# Bootstrap Artifact Spill",
                            "",
                            f"- artifact_key: `{artifact_key}`",
                            f"- original_workspace_path: `{workspace_path}`",
                            f"- spill_summary_path: `{spill_result.summary_path}`",
                            f"- spill_raw_path: `{spill_result.raw_path}`",
                            f"- original_size_chars: {len(content_text)}",
                            "",
                            "请优先继续读取上述 spill 文件。",
                        ]
                    )
                    + "\n",
                ),
                (spill_result.summary_path, spill_result.summary_content),
                (spill_result.raw_path, spill_result.raw_content),
            ]
        )
    return workspace_entries


def _build_session_bootstrap_workspace_files(
    *,
    session: ResearchSession,
    large_result_policy: Any,
) -> dict[str, str]:
    artifacts = _require_preloaded_session_artifacts(session)
    if not artifacts:
        return {}

    layout = build_research_workspace_layout(session.id)
    path_by_artifact_key = build_workspace_bootstrap_artifact_path_map(layout=layout)
    return dict(
        _build_bootstrap_workspace_file_entries(
            artifacts=artifacts,
            layout=layout,
            path_by_artifact_key=path_by_artifact_key,
            large_result_policy=large_result_policy,
        )
    )


@dataclass(slots=True)
class DeepResearchRuntimeRunner:
    runtime: DeepResearchRuntime
    workspace_files: dict[str, str]

    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> ResearchRuntimeRunResult:
        workspace_files = dict(self.workspace_files)
        workspace_files.update(
            _build_session_bootstrap_workspace_files(
                session=session,
                large_result_policy=self.runtime.config.large_result_policy,
            )
        )
        request_files = _build_runtime_request_files(
            workspace_files=workspace_files,
            session=session,
            plan_snapshot=plan_snapshot,
        )
        prompt = _build_runtime_prompt(
            session=session,
            plan_snapshot=plan_snapshot,
            workspace_paths=sorted(request_files),
        )
        request: dict[str, Any] = {
            "messages": [{"role": "user", "content": prompt}],
            "files": request_files,
        }
        config = self.runtime.make_run_config(thread_id=session.thread_id)
        started_at = perf_counter()
        ainvoke = getattr(self.runtime.agent, "ainvoke", None)
        if callable(ainvoke):
            result = await ainvoke(request, config)
        else:  # pragma: no cover - CompiledStateGraph 默认提供 ainvoke
            result = await asyncio.to_thread(self.runtime.agent.invoke, request, config)
        latency_ms = int((perf_counter() - started_at) * 1000)
        if not isinstance(result, dict):
            raise RuntimeError("Deep Research runtime 返回类型不符合预期")

        structured_payload = result.get("structured_response")
        if structured_payload is None:
            raise RuntimeError("Deep Research runtime 未返回 structured_response")
        try:
            structured = DeepResearchStructuredResponse.model_validate(
                _normalize_structured_response_payload(structured_payload)
            )
        except ValidationError as exc:
            raise RuntimeError("Deep Research runtime structured_response 不符合契约") from exc

        workspace_only_web_citations = (
            bool(structured.citations)
            and all(
                citation.source_type == ResearchSourceType.WEB
                and citation.source_provider == "workspace"
                for citation in structured.citations
            )
        )

        source_bundle = ResearchSourceBundleBuilder().build(
            target_sources=plan_snapshot.target_sources,
            citations=structured.citations,
            findings=structured.findings,
            required_web_providers=(
                select_required_web_providers(
                    complexity=plan_snapshot.complexity.value,
                    available_providers=self.runtime.tool_groups["web_provider_ids"],
                )
                if ResearchSourceTarget.WEB in set(plan_snapshot.target_sources)
                and not workspace_only_web_citations
                else ()
            ),
        )
        return ResearchRuntimeRunResult(
            source_bundle=source_bundle,
            latency_ms=latency_ms,
        )


async def build_deep_research_runtime_runner(
    *,
    settings: Settings,
    http_client: Any | None = None,
    redis: RedisClient | None = None,
) -> DeepResearchRuntimeRunner:
    prompt_loader = get_prompt_loader()
    runtime_config = ResearchRuntimeConfig(
        primary_model=create_chat_model(
            settings=settings,
            use_previous_response_id=False,
        ),
        subagent_model=create_chat_model(
            settings=settings,
            use_previous_response_id=False,
        ),
        finalizer_model=create_chat_model(
            settings=settings,
            use_previous_response_id=False,
        ),
        system_prompt=prompt_loader.render_with_few_shot("research/runtime_system"),
        memory_paths=(),
        skill_paths=(),
    )
    runtime = await create_deep_research_runtime(
        settings=settings,
        config=runtime_config,
        # 运行时先接受缺少 origin_url 的 citation 草稿，随后在 runner 侧统一补齐并
        # 收敛到严格的 DeepResearchStructuredResponse 契约，避免模型输出因细小字段遗漏
        # 被 runtime 提前拒绝。
        response_format=DeepResearchStructuredResponseDraft,
        http_client=http_client,
        redis=redis,
        checkpointer=MemorySaver(),
        store=InMemoryStore(),
    )
    return DeepResearchRuntimeRunner(
        runtime=runtime,
        workspace_files=_build_workspace_context_files(),
    )

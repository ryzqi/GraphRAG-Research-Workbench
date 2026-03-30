"""Deep Research runtime 单入口。"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from deepagents.backends.utils import create_file_data
from langchain.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tool_calling.registry import (
    ToolMeta,
    build_research_tool_registry,
)
from app.core.settings import Settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.chat_model_factory import create_chat_model
from app.integrations.mcp_adapters import McpToolEntry
from app.integrations.milvus_client import MilvusClient
from app.integrations.redis_client import RedisClient
from app.models.knowledge_base import KnowledgeBase
from app.models.research_session import ResearchSession
from app.models.tool_extension import ToolExtension
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
)
from app.services.research_observability import ResearchRuntimeRunResult
from app.services.research_runtime_types import (
    DEFAULT_RESEARCH_BACKEND_POLICY,
    ResearchBackendPolicy,
    ResearchRuntimeConfig,
    ResearchToolRegistryBundle,
)
from app.services.retrieval_service import RetrievalResult, RetrievalService
from app.services.research_source_bundle import ResearchSourceBundleBuilder

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
_DEFAULT_RESEARCH_SYSTEM_PROMPT = """
你是当前仓库的 Deep Research runtime。

执行规则：
1. 先读取 /workspace/context 下已提供的仓库文档；只有这些文档不足以回答问题时，才调用外部 research tools。
2. 结论必须直接锚定可核查证据；禁止编造 citation。
3. 返回结构化结果时，至少给出 2 条 findings 与 2 条 citations。
4. 如果引用 workspace 文档，统一使用：
   - source_type=web
   - source_provider=workspace
   - retrieval_method=read_file
   - source_id 为 workspace 文件路径
   - url / origin_url 为对应的 file:// URL
5. 如果引用 /workspace/context/kb_context.md 中的内部知识，统一使用：
   - source_type=kb
   - source_provider=kb
   - retrieval_method=kb_retrieve
   - source_id 为对应片段条目的 source_id
6. 只保留当前实现语义；不要为旧 research 路径补兼容说明。
""".strip()


class DeepResearchStructuredResponse(BaseModel):
    findings: list[str] = Field(min_length=2)
    citations: list[ResearchCanonicalCitation] = Field(min_length=2)


@dataclass(slots=True)
class ResearchKbContextLoader:
    db: AsyncSession
    milvus: MilvusClient
    embedding: EmbeddingClient
    redis: RedisClient | None = None
    top_k: int = 4

    async def load(self, *, session: ResearchSession) -> str | None:
        selected_kb_ids = [uuid.UUID(str(kb_id)) for kb_id in (session.selected_kb_ids or [])]
        if not selected_kb_ids:
            return None

        stmt = select(KnowledgeBase).where(KnowledgeBase.id.in_(selected_kb_ids))
        kb_items = (await self.db.execute(stmt)).scalars().all()
        kb_by_id = {item.id: item for item in kb_items}

        retrieval = RetrievalService(
            self.db,
            self.milvus,
            self.embedding,
            self.redis,
        )
        results = await retrieval.retrieve(
            query=session.question,
            kb_ids=selected_kb_ids,
            top_k=max(1, int(self.top_k)),
        )
        return self._render_markdown(
            question=session.question,
            selected_kb_ids=selected_kb_ids,
            kb_by_id=kb_by_id,
            results=results,
        )

    @staticmethod
    def _render_locator(locator: dict[str, Any] | None) -> str | None:
        if not isinstance(locator, dict) or not locator:
            return None
        return json.dumps(locator, ensure_ascii=False, sort_keys=True)

    @classmethod
    def _render_markdown(
        cls,
        *,
        question: str,
        selected_kb_ids: Sequence[uuid.UUID],
        kb_by_id: dict[uuid.UUID, KnowledgeBase],
        results: Sequence[RetrievalResult],
    ) -> str:
        lines = [
            "# 内部知识库上下文",
            "",
            "> 如果引用本文件中的内部知识，请使用：source_type=kb, source_provider=kb, retrieval_method=kb_retrieve，并把 source_id 填成对应片段条目的 source_id。",
            "",
            f"当前问题：{question}",
            "",
            "## 选中知识库",
        ]
        for kb_id in selected_kb_ids:
            kb = kb_by_id.get(kb_id)
            if kb is None:
                lines.append(f"- 未找到知识库元数据：{kb_id}")
                continue
            lines.append(f"- {kb.name} ({kb.id})")
            if kb.description:
                lines.append(f"  - description: {kb.description}")
            lines.append(f"  - readiness: {kb.readiness.value}")
            lines.append(f"  - status: {kb.status.value}")

        lines.extend(["", "## 查询相关片段"])
        if not results:
            lines.append("- 未检索到与当前问题直接相关的内部片段；保留知识库元数据供 runtime 参考。")
            return "\n".join(lines)

        for index, result in enumerate(results, start=1):
            chunk = result.chunk
            kb = kb_by_id.get(chunk.kb_id)
            excerpt = RetrievalService._result_excerpt(result) or "（空片段）"
            lines.extend(
                [
                    "",
                    f"### 片段 {index}",
                    f"- source_id: {chunk.id}",
                    f"- kb_id: {chunk.kb_id}",
                    f"- kb_name: {kb.name if kb is not None else 'unknown'}",
                    f"- material_id: {chunk.material_id}",
                    f"- score: {float(result.score):.4f}",
                ]
            )
            if chunk.heading_path:
                lines.append(f"- heading_path: {chunk.heading_path}")
            locator = cls._render_locator(chunk.locator)
            if locator:
                lines.append(f"- locator: {locator}")
            lines.extend(
                [
                    "- excerpt:",
                    "```text",
                    excerpt,
                    "```",
                ]
            )
        return "\n".join(lines)


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
        "backend": build_research_backend_factory(config.backend_policy),
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


def _build_runtime_prompt(
    *,
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
    workspace_paths: Sequence[str],
) -> str:
    route_hint = ", ".join(resolve_source_subagent_route(plan_snapshot.target_sources))
    lines = [
        "请执行当前 deep research runtime，并返回结构化结果。",
        f"问题：{session.question}",
        f"research_brief：{plan_snapshot.research_brief}",
        f"target_sources：{', '.join(item.value for item in plan_snapshot.target_sources)}",
        f"route_hint：{route_hint}",
    ]
    if workspace_paths:
        lines.extend(
            [
                "优先阅读以下 workspace 文档：",
                *[f"- {path}" for path in workspace_paths],
            ]
        )
    if "/workspace/context/kb_context.md" in workspace_paths:
        lines.extend(
            [
                "如果使用 /workspace/context/kb_context.md 中的内部知识片段，请确保 citation 满足：",
                "- source_type=kb",
                "- source_provider=kb",
                "- retrieval_method=kb_retrieve",
                "- source_id 使用该文件中对应片段条目的 source_id",
            ]
        )
    lines.extend(
        [
            "输出要求：",
            "- findings 至少 2 条，必须是可验证的具体结论。",
            "- citations 至少 2 条，必须与 findings 对应。",
            "- 如果 workspace 文档足够回答，不要为了凑工具而调用外部 provider。",
            "- 如果 workspace 文档不足，可再调用 Tavily / Jina Reader / SearXNG / arXiv 工具补证据。",
        ]
    )
    return "\n".join(lines)


def _build_runtime_request_files(
    *,
    workspace_files: dict[str, str],
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
    kb_context: str | None = None,
) -> dict[str, dict[str, Any]]:
    request_files = {
        path: create_file_data(content)
        for path, content in workspace_files.items()
    }
    request_files["/workspace/context/session_question.txt"] = create_file_data(session.question)
    request_files["/workspace/context/plan_snapshot.json"] = create_file_data(
        json.dumps(plan_snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2)
    )
    if kb_context and kb_context.strip():
        request_files["/workspace/context/kb_context.md"] = create_file_data(kb_context)
    return request_files


@dataclass(slots=True)
class DeepResearchRuntimeRunner:
    runtime: DeepResearchRuntime
    workspace_files: dict[str, str]
    kb_context_loader: ResearchKbContextLoader | None = None

    async def run_session(
        self,
        *,
        session: ResearchSession,
        plan_snapshot: ResearchPlanSnapshot,
    ) -> ResearchRuntimeRunResult:
        kb_context = await self._load_kb_context(session=session)
        request_files = _build_runtime_request_files(
            workspace_files=self.workspace_files,
            session=session,
            plan_snapshot=plan_snapshot,
            kb_context=kb_context,
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
            structured = DeepResearchStructuredResponse.model_validate(structured_payload)
        except ValidationError as exc:
            raise RuntimeError("Deep Research runtime structured_response 不符合契约") from exc

        source_bundle = ResearchSourceBundleBuilder().build(
            target_sources=plan_snapshot.target_sources,
            citations=structured.citations,
            findings=structured.findings,
            required_web_providers=(),
        )
        return ResearchRuntimeRunResult(
            source_bundle=source_bundle,
            latency_ms=latency_ms,
        )

    async def _load_kb_context(self, *, session: ResearchSession) -> str | None:
        if self.kb_context_loader is None:
            return None
        return await self.kb_context_loader.load(session=session)


async def build_deep_research_runtime_runner(
    *,
    settings: Settings,
    db: AsyncSession | None = None,
    http_client: Any | None = None,
    redis: RedisClient | None = None,
    milvus: MilvusClient | None = None,
    embedding: EmbeddingClient | None = None,
) -> DeepResearchRuntimeRunner:
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
        system_prompt=_DEFAULT_RESEARCH_SYSTEM_PROMPT,
        memory_paths=(),
        skill_paths=(),
    )
    runtime = await create_deep_research_runtime(
        settings=settings,
        config=runtime_config,
        response_format=DeepResearchStructuredResponse,
        http_client=http_client,
        redis=redis,
        checkpointer=MemorySaver(),
        store=InMemoryStore(),
    )
    kb_context_loader = None
    if db is not None and milvus is not None and embedding is not None:
        kb_context_loader = ResearchKbContextLoader(
            db=db,
            milvus=milvus,
            embedding=embedding,
            redis=redis,
        )
    return DeepResearchRuntimeRunner(
        runtime=runtime,
        workspace_files=_build_workspace_context_files(),
        kb_context_loader=kb_context_loader,
    )

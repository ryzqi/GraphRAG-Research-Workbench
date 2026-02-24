"""DeepAgents 深度研究代理封装。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from deepagents import create_deep_agent
from langchain.tools import BaseTool, tool as lc_tool
from pydantic import BaseModel, Field

from app.agents.deepagents_io import build_user_messages, extract_last_message_text
from app.agents.memory_backend import MemoryBackendFactory
from app.agents.tools.report_generate import build_report_generate_tool
from app.agents.tools.research_plan import build_research_plan_tool
from app.agents.tools.subagent_coordinate import build_subagent_coordinate_tool
from app.agents.tools.system_time import build_system_time_tool
from app.agents.tools.web_search import (
    build_web_crawl_tool,
    build_web_extract_tool,
    build_web_research_tool,
    build_web_search_tool,
)
from app.core.settings import get_settings
from app.integrations.chat_model_factory import create_chat_model
from app.integrations.llm_client import LLMClient
from app.integrations.redis_client import RedisClient
from app.models.tool_extension import ToolExtension
from app.prompts import get_prompt_loader
from app.services.retrieval_service import RetrievalResult, RetrievalService


@dataclass
class DeepResearchOutput:
    """深度研究输出。"""

    report_md: str
    citations: list[dict]
    retrieval_results: list[RetrievalResult] = field(default_factory=list)
    stage_summaries: dict[str, object] = field(default_factory=dict)


class RetrievalArgs(BaseModel):
    """检索工具参数。"""

    query: str = Field(..., description="检索问题")
    kb_ids: list[str] | None = Field(default=None, description="知识库 ID 列表")
    top_k: int | None = Field(default=None, description="返回条数")


class DeepResearchAgent:
    """DeepAgents 深度研究代理。"""

    def __init__(
        self,
        retrieval: RetrievalService,
        extensions: list[ToolExtension],
        *,
        redis: RedisClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = get_settings()
        self._retrieval = retrieval
        self._extensions = extensions
        self._prompts = get_prompt_loader()
        self._model = create_chat_model(settings=self._settings)
        self._retrieval_results: list[RetrievalResult] = []
        self._stage_summaries: dict[str, object] = {}
        self._redis = redis
        self._http_client = http_client

    def _reset_run_state(self) -> None:
        self._retrieval_results = []
        self._stage_summaries = {}

    def _format_results(self, results: list[RetrievalResult]) -> str:
        if not results:
            return "未检索到相关内容。"
        return "\n\n".join(
            f"[{i}] {r.context_text or r.chunk.content}" for i, r in enumerate(results, 1)
        )

    def _build_citations(self) -> list[dict]:
        citations: list[dict] = []
        for i, r in enumerate(self._retrieval_results, 1):
            citations.append(
                {
                    "index": i,
                    "kb_id": str(r.chunk.kb_id),
                    "material_id": str(r.chunk.material_id),
                    "chunk_id": str(r.chunk.id),
                    "excerpt": r.chunk.content[:200],
                    "locator": r.chunk.locator,
                }
            )
        return citations

    def _extract_report(self, result: object) -> str:
        return extract_last_message_text(result)

    def _build_retrieval_tool(
        self, default_kb_ids: list[uuid.UUID]
    ) -> BaseTool:
        default_kb_list = [str(kid) for kid in default_kb_ids]
        settings = self._settings

        async def _retrieve(
            query: str,
            kb_ids: list[str] | None = None,
            top_k: int | None = None,
        ) -> str:
            resolved = kb_ids or default_kb_list
            resolved_ids: list[uuid.UUID] = []
            for kid in resolved:
                try:
                    resolved_ids.append(uuid.UUID(str(kid)))
                except ValueError:
                    continue
            if not resolved_ids:
                resolved_ids = default_kb_ids

            results = await self._retrieval.retrieve(
                query=query,
                kb_ids=resolved_ids,
                top_k=top_k or settings.retrieval_default_top_k,
            )
            self._retrieval_results.extend(results)
            self._stage_summaries["retrieval"] = {
                "count": len(self._retrieval_results),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            return self._format_results(results)

        return lc_tool(
            "kb_retrieve",
            description="从知识库检索资料，返回带编号的引用片段。",
            args_schema=RetrievalArgs,
        )(_retrieve)

    def _build_llm_client(self) -> LLMClient:
        """构建 LLM 客户端用于工具。"""
        return LLMClient()

    async def run(
        self,
        *,
        question: str,
        kb_ids: list[uuid.UUID],
        allow_external: bool,
        thread_id: str | None = None,
        enable_subagents: bool = False,
    ) -> DeepResearchOutput:
        """执行深度研究流程。"""
        self._reset_run_state()
        system_prompt = self._prompts.render_with_few_shot(
            "research/deep_agent_system", question=question
        )

        llm_client = self._build_llm_client()
        tools: list[BaseTool] = [
            self._build_retrieval_tool(kb_ids),
            build_system_time_tool(),
            build_research_plan_tool(llm_client, self._prompts),
            build_report_generate_tool(llm_client, self._prompts),
        ]

        if allow_external:
            if self._settings.web_search_api_key:
                tools.append(
                    build_web_search_tool(
                        self._settings,
                        redis=self._redis,
                        http_client=self._http_client,
                    )
                )
                tools.append(
                    build_web_extract_tool(
                        self._settings,
                        redis=self._redis,
                        http_client=self._http_client,
                    )
                )
                tools.append(
                    build_web_crawl_tool(
                        self._settings,
                        redis=self._redis,
                        http_client=self._http_client,
                    )
                )
                tools.append(
                    build_web_research_tool(
                        self._settings,
                        redis=self._redis,
                        http_client=self._http_client,
                    )
                )

        if enable_subagents:
            tools.append(build_subagent_coordinate_tool(model=self._model))

        memory_factory = MemoryBackendFactory.from_settings(self._settings)
        agent = create_deep_agent(
            model=self._model,
            tools=tools,
            system_prompt=system_prompt,
            store=memory_factory.store,
            backend=memory_factory.build_backend(),
        )

        config = {"configurable": {"thread_id": thread_id}} if thread_id else None
        result = await agent.ainvoke(build_user_messages(question), config=config)
        report_md = self._extract_report(result)
        citations = self._build_citations()

        self._stage_summaries["draft"] = {
            "citation_count": len(citations),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        return DeepResearchOutput(
            report_md=report_md,
            citations=citations,
            retrieval_results=self._retrieval_results,
            stage_summaries=self._stage_summaries,
        )

"""DeepAgents 深度研究代理封装。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from deepagents import create_deep_agent
from langchain_core.tools import BaseTool, StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agents.memory_backend import MemoryBackendFactory
from app.agents.mcp_tools import build_mcp_tools
from app.core.settings import get_settings
from app.integrations.mcp_client import MCPClient
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
        mcp: MCPClient,
        extensions: list[ToolExtension],
    ) -> None:
        self._settings = get_settings()
        self._retrieval = retrieval
        self._mcp = mcp
        self._extensions = extensions
        self._prompts = get_prompt_loader()
        self._model = ChatOpenAI(
            model=self._settings.llm_model,
            api_key=self._settings.llm_api_key,
            base_url=self._settings.llm_base_url.rstrip("/"),
        )
        self._retrieval_results: list[RetrievalResult] = []
        self._stage_summaries: dict[str, object] = {}

    def _reset_run_state(self) -> None:
        self._retrieval_results = []
        self._stage_summaries = {}

    def _format_results(self, results: list[RetrievalResult]) -> str:
        if not results:
            return "未检索到相关内容。"
        return "\n\n".join(
            f"[{i}] {r.chunk.text}" for i, r in enumerate(results, 1)
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
                    "excerpt": r.chunk.text[:200],
                    "locator": r.chunk.locator,
                }
            )
        return citations

    def _extract_report(self, result: object) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            if "output" in result:
                return str(result["output"])
            if "content" in result:
                return str(result["content"])
        return str(result)

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

        return StructuredTool.from_function(
            name="kb_retrieve",
            description="从知识库检索资料，返回带编号的引用片段。",
            args_schema=RetrievalArgs,
            coroutine=_retrieve,
        )

    async def run(
        self,
        *,
        question: str,
        kb_ids: list[uuid.UUID],
        allow_external: bool,
        thread_id: str | None = None,
    ) -> DeepResearchOutput:
        """执行深度研究流程。"""
        self._reset_run_state()
        system_prompt = self._prompts.render(
            "research/deep_agent_system", question=question
        )

        tools: list[BaseTool] = [self._build_retrieval_tool(kb_ids)]
        if allow_external and self._extensions:
            tools.extend(await build_mcp_tools(self._mcp, self._extensions))

        memory_factory = MemoryBackendFactory.from_settings(self._settings)
        agent = create_deep_agent(
            model=self._model,
            tools=tools,
            system_prompt=system_prompt,
            store=memory_factory.store,
            backend=memory_factory.build_backend(),
        )

        if thread_id:
            result = await agent.ainvoke(
                {"input": question},
                config={"configurable": {"thread_id": thread_id}},
            )
        else:
            result = await agent.ainvoke({"input": question})
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

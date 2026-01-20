"""研究链路 LangGraph 实现（ToolNode + 工具调用）。

该图用于替换 DeepAgents 研究链路：
- 复用研究工具（research_plan/evidence_compare/report_generate）
- 复用 kb_retrieve/web_search/MCP 扩展工具
- 不触发人工审批（Worker 自动执行）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Annotated, TypedDict, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.message import add_messages

from app.agents.tool_calling.builder import ToolCallingGraphBuilder
from app.agents.tool_calling.registry import build_tool_registry
from app.agents.tools.evidence_compare import build_evidence_compare_tool
from app.agents.tools.kb_retrieve import build_kb_retrieve_tool
from app.agents.tools.report_generate import build_report_generate_tool
from app.agents.tools.research_plan import build_research_plan_tool
from app.core.settings import get_settings
from app.integrations.llm_client import LLMClient
from app.integrations.mcp_client import MCPClient
from app.models.tool_extension import ToolExtension
from app.prompts import get_prompt_loader
from app.services.context_builder import ContextBuilder
from app.services.retrieval_service import RetrievalResult, RetrievalService


class ResearchState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    pending_tool_calls: list[dict]
    stage_summaries: dict[str, Any]
    metrics: dict[str, Any]


@dataclass
class ResearchOutput:
    report_md: str
    citations: list[dict]
    retrieval_results: list[RetrievalResult] = field(default_factory=list)
    stage_summaries: dict[str, object] = field(default_factory=dict)
    metrics: dict[str, object] = field(default_factory=dict)



class ResearchGraph:
    """研究图：ToolNode loop + 研究工具集合。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._prompts = get_prompt_loader()
        self._context_builder = ContextBuilder(self._settings)

    @staticmethod
    def _build_citations(results: list[RetrievalResult]) -> list[dict]:
        citations: list[dict] = []
        for i, r in enumerate(results, 1):
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

    async def build_runtime(
        self,
        *,
        question: str,
        kb_ids: list[uuid.UUID],
        retrieval: RetrievalService,
        mcp: MCPClient,
        extensions: list[ToolExtension],
        allow_external: bool,
        thread_id: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> tuple[Any, ResearchState, dict[str, Any] | None, list[RetrievalResult]]:
        """构建研究图执行上下文（供流式/非流式复用）。"""
        retrieval_results: list[RetrievalResult] = []
        seen_chunk_ids: set[uuid.UUID] = set()

        def _on_results(included: list[RetrievalResult], _meta: dict[str, Any]) -> None:
            for r in included:
                if r.chunk.id not in seen_chunk_ids:
                    retrieval_results.append(r)
                    seen_chunk_ids.add(r.chunk.id)

        kb_tool = build_kb_retrieve_tool(
            retrieval=retrieval,
            default_kb_ids=kb_ids,
            context_builder=self._context_builder,
            on_results=_on_results,
        )

        llm_client = LLMClient(
            base_url=self._settings.llm_base_url,
            api_key=self._settings.llm_api_key,
            model=self._settings.llm_model,
        )
        internal_tools = [
            kb_tool,
            build_research_plan_tool(llm_client, self._prompts),
            build_evidence_compare_tool(llm_client, self._prompts),
            build_report_generate_tool(llm_client, self._prompts),
        ]

        tools, tool_meta_by_name = await build_tool_registry(
            settings=self._settings,
            mcp=mcp,
            extensions=extensions,
            extra_tools=internal_tools,
            include_web_search=allow_external,
            include_mcp=allow_external,
        )

        chat_model = ChatOpenAI(
            model=self._settings.llm_model,
            api_key=self._settings.llm_api_key,
            base_url=self._settings.llm_base_url.rstrip("/"),
        )

        system_prompt = self._prompts.render("research/deep_agent_system", question=question)
        state: ResearchState = {
            "messages": [SystemMessage(content=system_prompt), HumanMessage(content=question)],
            "pending_tool_calls": [],
            "stage_summaries": {},
            "metrics": {},
        }

        graph = ToolCallingGraphBuilder(
            state_schema=ResearchState,
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
            require_human_review=False,
            messages_key="messages",
        ).build()

        compiled = graph.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}} if thread_id else None
        return compiled, state, config, retrieval_results

    def build_output(
        self, result_dict: dict[str, Any], retrieval_results: list[RetrievalResult]
    ) -> ResearchOutput:
        """基于运行结果构建研究输出。"""
        report_md = ""
        messages = result_dict.get("messages")
        if isinstance(messages, list):
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    report_md = str(msg.content or "")
                    break

        citations = self._build_citations(retrieval_results)

        stage_summaries = result_dict.get("stage_summaries")
        if not isinstance(stage_summaries, dict):
            stage_summaries = {}
        stage_summaries = {
            **stage_summaries,
            "retrieval": {
                "count": len(retrieval_results),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
            "draft": {
                "citation_count": len(citations),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        metrics = result_dict.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}

        return ResearchOutput(
            report_md=report_md,
            citations=citations,
            retrieval_results=retrieval_results,
            stage_summaries=stage_summaries,
            metrics=metrics,
        )

    async def run(
        self,
        *,
        question: str,
        kb_ids: list[uuid.UUID],
        retrieval: RetrievalService,
        mcp: MCPClient,
        extensions: list[ToolExtension],
        allow_external: bool,
        thread_id: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> ResearchOutput:
        """执行研究图。"""
        compiled, state, config, retrieval_results = await self.build_runtime(
            question=question,
            kb_ids=kb_ids,
            retrieval=retrieval,
            mcp=mcp,
            extensions=extensions,
            allow_external=allow_external,
            thread_id=thread_id,
            checkpointer=checkpointer,
        )
        result = await compiled.ainvoke(state, config)
        result_dict = cast(dict[str, Any], result)
        return self.build_output(result_dict, retrieval_results)

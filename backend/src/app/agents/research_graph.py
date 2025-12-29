"""深度研究代理封装（DeepAgents）。"""

from __future__ import annotations

import uuid

from app.agents.deep_research_agent import DeepResearchAgent, DeepResearchOutput
from app.integrations.mcp_client import MCPClient
from app.models.tool_extension import ToolExtension
from app.services.retrieval_service import RetrievalService


class ResearchGraph:
    """兼容旧调用路径的深度研究入口。"""

    def __init__(
        self,
        retrieval: RetrievalService,
        mcp: MCPClient,
        extensions: list[ToolExtension],
    ) -> None:
        self._agent = DeepResearchAgent(
            retrieval=retrieval,
            mcp=mcp,
            extensions=extensions,
        )

    async def run(
        self,
        *,
        question: str,
        kb_ids: list[uuid.UUID],
        allow_external: bool,
        thread_id: str | None = None,
    ) -> DeepResearchOutput:
        return await self._agent.run(
            question=question,
            kb_ids=kb_ids,
            allow_external=allow_external,
            thread_id=thread_id,
        )

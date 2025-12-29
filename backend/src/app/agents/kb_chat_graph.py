"""知识库问答 LangGraph 实现。

将知识库问答流程转换为 LangGraph 图，支持检查点持久化。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from app.integrations.llm_client import ChatMessage as LLMMessage
from app.integrations.llm_client import LLMClient
from app.prompts import get_prompt_loader
from app.services.retrieval_service import RetrievalResult, RetrievalService


@dataclass
class KbChatState:
    """知识库问答状态。"""

    question: str
    kb_ids: list[uuid.UUID]
    history: list[LLMMessage] = field(default_factory=list)

    # 阶段输出
    retrieval_results: list[RetrievalResult] = field(default_factory=list)
    context: str = ""
    answer: str = ""

    # 元数据
    stage_summaries: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class KbChatGraph:
    """知识库问答 LangGraph 图。"""

    def __init__(self, llm: LLMClient, retrieval: RetrievalService) -> None:
        self._llm = llm
        self._retrieval = retrieval
        self._prompts = get_prompt_loader()
        self._graph_builder = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """构建问答图。"""
        graph = StateGraph(KbChatState)

        graph.add_node("retrieve", self._retrieve_node)
        graph.add_node("generate", self._generate_node)

        graph.set_entry_point("retrieve")
        graph.add_edge("retrieve", "generate")
        graph.add_edge("generate", END)

        return graph

    def compile(self, checkpointer: BaseCheckpointSaver | None = None):
        """编译图。"""
        return self._graph_builder.compile(checkpointer=checkpointer)

    async def run(
        self,
        state: KbChatState,
        thread_id: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> KbChatState:
        """执行问答流程。"""
        compiled = self.compile(checkpointer)
        config = {"configurable": {"thread_id": thread_id}} if thread_id else None
        return await compiled.ainvoke(state, config)

    async def _retrieve_node(self, state: KbChatState) -> dict:
        """检索节点。"""
        results = await self._retrieval.retrieve(
            query=state.question,
            kb_ids=state.kb_ids,
            top_k=5,
        )

        context_parts = [f"[{i}] {r.chunk.text}" for i, r in enumerate(results, 1)]
        context = "\n\n".join(context_parts) if context_parts else "（未找到相关内容）"

        return {
            "retrieval_results": results,
            "context": context,
            "stage_summaries": {
                "retrieval": {
                    "count": len(results),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        }

    async def _generate_node(self, state: KbChatState) -> dict:
        """生成节点。"""
        system_prompt = self._prompts.render("kb_chat/system", context=state.context)

        messages = [
            LLMMessage(role="system", content=system_prompt),
            *state.history,
            LLMMessage(role="user", content=state.question),
        ]

        response = await self._llm.chat_with_metrics(messages=messages)

        return {
            "answer": response.content,
            "stage_summaries": {
                **state.stage_summaries,
                "generation": {
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        }

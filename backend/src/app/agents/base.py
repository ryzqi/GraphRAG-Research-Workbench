"""代理基类模块。

提供统一的 Agent 图基类，支持日志、指标收集和追踪。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph

from app.integrations.llm_client import LLMClient
from app.prompts import get_prompt_loader

logger = logging.getLogger(__name__)

StateT = TypeVar("StateT")


@dataclass
class BaseAgentState:
    """代理状态基类。"""

    question: str
    stage_summaries: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def record_stage(self, stage: str, **extra: Any) -> dict[str, Any]:
        """记录阶段完成。"""
        return {
            **self.stage_summaries,
            stage: {
                "completed_at": datetime.now(timezone.utc).isoformat(),
                **extra,
            },
        }


class BaseAgentGraph(ABC, Generic[StateT]):
    """代理图基类。"""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._prompts = get_prompt_loader()
        self._graph_builder = self._build_graph()

    @abstractmethod
    def _build_graph(self) -> StateGraph:
        """构建图（子类实现）。"""
        ...

    @abstractmethod
    def _get_state_class(self) -> type[StateT]:
        """获取状态类（子类实现）。"""
        ...

    def compile(self, checkpointer: BaseCheckpointSaver | None = None):
        """编译图。"""
        return self._graph_builder.compile(checkpointer=checkpointer)

    async def run(
        self,
        state: StateT,
        thread_id: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> StateT:
        """执行图。"""
        compiled = self.compile(checkpointer)
        config = {"configurable": {"thread_id": thread_id}} if thread_id else None

        logger.info(
            "Agent 开始执行",
            extra={
                "agent_type": self.__class__.__name__,
                "thread_id": thread_id,
            },
        )

        try:
            result = await compiled.ainvoke(state, config)
            logger.info(
                "Agent 执行完成",
                extra={"agent_type": self.__class__.__name__},
            )
            return result
        except Exception as e:
            logger.error(
                f"Agent 执行失败: {e}",
                extra={"agent_type": self.__class__.__name__},
            )
            raise

    def _log_node_start(self, node_name: str) -> None:
        """记录节点开始。"""
        logger.debug(f"节点开始: {node_name}", extra={"node": node_name})

    def _log_node_end(self, node_name: str, **metrics: Any) -> None:
        """记录节点结束。"""
        logger.debug(f"节点结束: {node_name}", extra={"node": node_name, **metrics})

"""KB Chat agentic LangGraph：preprocess -> retrieval -> reflection -> answer。"""

from __future__ import annotations

from functools import partial
from typing import Any, cast

from langchain.tools import BaseTool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import RetryPolicy

from app.agents.answer_subgraph import build_answer_subgraph
from app.agents.kb_chat_agentic.reflection import (
    route_after_answer_review,
    transform_query_for_retry,
)
from app.agents.kb_chat_agentic.tool_loop import force_exit_node
from app.agents.kb_chat_agentic_graph_runtime import (
    KbChatGraphContext,
    build_kb_chat_run_config,
    build_kb_chat_run_context,
)
from app.agents.kb_chat_agentic_state import (
    KbChatInputState,
    KbChatInternalState,
    KbChatOutputState,
    PreprocessRoutingInput,
    build_graph_input_state,
    resolve_routing_decision,
)
from app.agents.kb_chat_trace_nodes import (
    extend_kb_chat_node_metadata,
    wrap_kb_chat_node_with_io as shared_wrap_node_with_io,
)
from app.agents.preprocess_subgraph import build_preprocess_subgraph
from app.agents.retrieval_subgraph import build_retrieval_subgraph
from app.agents.tool_calling.registry import ToolMeta
from app.core.settings import get_settings


def _route_after_preprocess_subgraph(state: PreprocessRoutingInput) -> str:
    decision = resolve_routing_decision(state, "preprocess")
    next_node = str(decision.get("next_node") or "").strip().lower()
    if next_node in {"retrieval_subgraph", "transform_query", "force_exit"}:
        return next_node
    return "retrieval_subgraph"


def _wrap_node_with_io(node_name: str, node_callable: Any):
    return shared_wrap_node_with_io(node_name, node_callable)


class KbChatAgenticGraph:
    """Agentic KB Chat 图：preprocess → retrieval → reflection → answer。"""

    def __init__(
        self,
        *,
        chat_model: BaseChatModel,
        tools: list[BaseTool],
        tool_meta_by_name: dict[str, ToolMeta],  # kept for signature compatibility
        kb_chat_config: dict[str, Any] | None = None,
    ) -> None:
        del tool_meta_by_name  # not used in this stage (no human review)
        del kb_chat_config  # graph wiring currently only depends on settings/tool set
        settings = get_settings()
        self._settings = settings
        transform_retry_policy = RetryPolicy(
            max_attempts=max(
                2, int(getattr(settings, "kb_chat_max_retrieval_retries", 2)) + 1
            )
        )

        def node_metadata(
            node_id: str,
            *,
            side_effect_type: str,
            retry_policy: RetryPolicy | None = None,
            retry_disabled_reason: str | None = None,
        ) -> dict[str, Any]:
            metadata = extend_kb_chat_node_metadata(
                node_id,
                side_effect_type=side_effect_type,
                retry_enabled=retry_policy is not None,
            )
            if retry_policy is None:
                metadata["retry_disabled_reason"] = (
                    retry_disabled_reason or side_effect_type
                )
            return metadata

        graph = StateGraph(
            state_schema=KbChatInternalState,
            context_schema=KbChatGraphContext,
            input_schema=KbChatInputState,
            output_schema=KbChatOutputState,
        )

        kb_tool = next(
            (t for t in tools if getattr(t, "name", None) == "kb_retrieve"), None
        )
        if kb_tool is None:
            raise RuntimeError("kb_retrieve tool is required for agentic KB chat")

        preprocess_subgraph = build_preprocess_subgraph(settings=settings)
        retrieval_subgraph = build_retrieval_subgraph(
            settings=settings,
            kb_tool=kb_tool,
            chat_model=chat_model,
        )
        answer_subgraph = build_answer_subgraph(
            settings=settings,
            chat_model=chat_model,
        )
        graph.add_node(
            "preprocess_subgraph",
            _wrap_node_with_io("preprocess_subgraph", preprocess_subgraph),
            metadata=node_metadata("preprocess_subgraph", side_effect_type="subgraph"),
        )
        graph.add_node(
            "retrieval_subgraph",
            _wrap_node_with_io("retrieval_subgraph", retrieval_subgraph),
            metadata=node_metadata("retrieval_subgraph", side_effect_type="subgraph"),
        )
        graph.add_node(
            "answer_subgraph",
            _wrap_node_with_io("answer_subgraph", answer_subgraph),
            metadata=node_metadata("answer_subgraph", side_effect_type="subgraph"),
        )
        graph.add_node(
            "transform_query",
            _wrap_node_with_io(
                "transform_query",
                partial(transform_query_for_retry, settings=settings),
            ),
            metadata=node_metadata(
                "transform_query",
                side_effect_type="llm",
                retry_policy=transform_retry_policy,
            ),
            retry_policy=transform_retry_policy,
        )
        graph.add_node(
            "force_exit",
            _wrap_node_with_io(
                "force_exit",
                partial(force_exit_node, settings=settings),
            ),
            metadata=node_metadata("force_exit", side_effect_type="deterministic_rule"),
        )
        graph.set_entry_point("preprocess_subgraph")
        graph.add_conditional_edges(
            "preprocess_subgraph",
            _route_after_preprocess_subgraph,
            {
                "retrieval_subgraph": "retrieval_subgraph",
                "transform_query": "transform_query",
                "force_exit": "force_exit",
            },
        )
        graph.add_edge("retrieval_subgraph", "answer_subgraph")
        graph.add_edge("transform_query", "retrieval_subgraph")
        graph.add_conditional_edges(
            "answer_subgraph",
            lambda s: route_after_answer_review(s, settings),
            {
                "END": END,
                "transform_query": "transform_query",
                "force_exit": "force_exit",
            },
        )
        graph.add_edge("force_exit", END)
        self._graph_builder = graph

    def compile(
        self,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
    ):
        return self._graph_builder.compile(
            checkpointer=checkpointer,
            store=store,
        )

    def make_run_config(self, thread_id: str | None = None) -> RunnableConfig:
        return build_kb_chat_run_config(
            thread_id=thread_id,
            recursion_limit=int(self._settings.kb_chat_graph_recursion_limit),
        )

    def make_run_context(
        self,
        *,
        thread_id: str | None = None,
        state: dict[str, Any] | None = None,
        user_id: str | None = None,
        kb_ids: list[str] | None = None,
        runtime_config: dict[str, Any] | None = None,
    ) -> KbChatGraphContext:
        return build_kb_chat_run_context(
            thread_id=thread_id,
            state=state,
            user_id=user_id,
            kb_ids=kb_ids,
            runtime_config=runtime_config,
            settings=self._settings,
        )

    async def run(
        self,
        state: dict,
        thread_id: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
        run_context: KbChatGraphContext | None = None,
    ) -> dict[str, Any]:
        compiled = self.compile(checkpointer=checkpointer, store=store)
        config = self.make_run_config(thread_id=thread_id)
        context = run_context or self.make_run_context(thread_id=thread_id, state=state)
        result = await compiled.ainvoke(
            build_graph_input_state(state),
            config,
            context=context,
        )
        return cast(dict[str, Any], result)

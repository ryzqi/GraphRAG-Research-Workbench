"""KB Chat agentic LangGraph (preprocess → retrieval → reflection → answer).

This graph follows the OpenSpec change `refactor-kb-agent-orchestration`:
- Preprocess: MergeContext → Coref → Ambiguity → Normalize → (Decomp|MultiQuery) → HyDE
- RetrievalLayer: run kb_retrieve once per round (Top-N context)
- ReflectionLayer: doc relevance → generation → hallucination check → answer check (with retries)

Notes:
- To keep streaming/service plumbing compatible, only the final answer is emitted as an AIMessage.
"""

from __future__ import annotations

from typing import Any, cast

from functools import partial

from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.store.base import BaseStore

from app.agents.kb_chat_agentic_state import KbChatAgenticState
from app.agents.tool_calling.registry import ToolMeta
from app.core.settings import get_settings

from app.agents.kb_chat_agentic.preprocess import (
    ambiguity_check,
    decomp_check_route,
    decomposition,
    entity_expand,
    generate_variants,
    hyde,
    hyde_check_route,
    merge_context,
    multi_query_check_route,
    normalize_rewrite,
    prepare_messages,
    coref_rewrite,
)
from app.agents.kb_chat_agentic.tool_loop import force_exit_node
from app.agents.kb_chat_agentic.reflection import (
    answer_check,
    doc_grader,
    finalize_answer,
    generate_draft,
    hallucination_check,
    kb_retrieve_context,
    route_after_answer_check,
    route_after_doc_grader,
    route_after_hallucination,
    transform_query_for_retry,
)


class KbChatAgenticGraph:
    """Agentic KB chat graph (preprocess → retrieval → reflection → answer)."""

    def __init__(
        self,
        *,
        chat_model: ChatOpenAI,
        tools: list[BaseTool],
        tool_meta_by_name: dict[str, ToolMeta],  # kept for signature compatibility
    ) -> None:
        del tool_meta_by_name  # not used in this stage (no human review)
        settings = get_settings()

        graph = StateGraph(KbChatAgenticState)

        # -----------------
        # Preprocess chain
        # -----------------
        graph.add_node("merge_context", partial(merge_context, settings=settings))
        graph.add_node("coref_rewrite", partial(coref_rewrite, settings=settings))
        graph.add_node("ambiguity_check", partial(ambiguity_check, settings=settings))
        graph.add_node("normalize_rewrite", partial(normalize_rewrite, settings=settings))
        graph.add_node("decomposition", partial(decomposition, settings=settings))
        graph.add_node("generate_variants", partial(generate_variants, settings=settings))
        graph.add_node("entity_expand", partial(entity_expand, settings=settings))
        graph.add_node("hyde", partial(hyde, settings=settings))
        graph.add_node("prepare_messages", partial(prepare_messages, settings=settings))

        # -----------------
        # Retrieval/Reflection
        # -----------------
        kb_tool = next((t for t in tools if getattr(t, "name", None) == "kb_retrieve"), None)
        if kb_tool is None:
            raise RuntimeError("kb_retrieve tool is required for agentic KB chat")

        graph.add_node("retrieve", partial(kb_retrieve_context, settings=settings, kb_tool=kb_tool))
        graph.add_node("doc_grader", partial(doc_grader, settings=settings, chat_model=chat_model))
        graph.add_node("transform_query", partial(transform_query_for_retry, settings=settings))
        graph.add_node(
            "generate",
            partial(generate_draft, settings=settings, chat_model=chat_model, strict=False),
        )
        graph.add_node(
            "generate_strict",
            partial(generate_draft, settings=settings, chat_model=chat_model, strict=True),
        )
        graph.add_node(
            "hallucination_check",
            partial(hallucination_check, settings=settings, chat_model=chat_model),
        )
        graph.add_node("answer_check", partial(answer_check, settings=settings, chat_model=chat_model))
        graph.add_node("finalize", finalize_answer)
        graph.add_node("force_exit", partial(force_exit_node, settings=settings))

        # Entry
        graph.set_entry_point("merge_context")
        graph.add_edge("merge_context", "coref_rewrite")
        graph.add_edge("coref_rewrite", "ambiguity_check")

        # Ambiguity routing (clarify => ForceExit)
        def _route_after_ambiguity(state: dict) -> str:
            reflection = state.get("reflection")
            action = reflection.get("action") if isinstance(reflection, dict) else None
            return "force_exit" if action == "clarify" else "normalize_rewrite"

        graph.add_conditional_edges(
            "ambiguity_check",
            _route_after_ambiguity,
            {"force_exit": "force_exit", "normalize_rewrite": "normalize_rewrite"},
        )

        # Decomposition vs MultiQuery (mutually exclusive; decomposition wins)
        graph.add_conditional_edges(
            "normalize_rewrite",
            lambda s: decomp_check_route(s, settings),
            {"decomposition": "decomposition", "multi_query_check": "multi_query_check"},
        )

        # MultiQuery check node (routing-only, no state updates)
        graph.add_node("multi_query_check", lambda _s: {})
        graph.add_conditional_edges(
            "multi_query_check",
            lambda s: multi_query_check_route(s, settings),
            {"generate_variants": "generate_variants", "hyde_check": "hyde_check"},
        )

        graph.add_edge("decomposition", "hyde_check")
        graph.add_edge("generate_variants", "entity_expand")
        graph.add_edge("entity_expand", "hyde_check")

        # HyDE check node (routing-only)
        graph.add_node("hyde_check", lambda _s: {})
        graph.add_conditional_edges(
            "hyde_check",
            lambda s: hyde_check_route(s, settings),
            {"hyde": "hyde", "prepare_messages": "prepare_messages"},
        )
        graph.add_edge("hyde", "prepare_messages")
        graph.add_edge("prepare_messages", "retrieve")
        graph.add_edge("retrieve", "doc_grader")

        # Doc relevance → Generate or TransformQuery
        graph.add_conditional_edges(
            "doc_grader",
            lambda s: route_after_doc_grader(s, settings),
            {"generate": "generate", "transform_query": "transform_query", "force_exit": "force_exit"},
        )

        graph.add_edge("transform_query", "retrieve")

        # Draft generation → Hallucination → AnswerCheck → Finalize
        graph.add_edge("generate", "hallucination_check")
        graph.add_edge("generate_strict", "hallucination_check")
        graph.add_conditional_edges(
            "hallucination_check",
            lambda s: route_after_hallucination(s, settings),
            {
                "answer_check": "answer_check",
                "generate_strict": "generate_strict",
                "transform_query": "transform_query",
                "force_exit": "force_exit",
            },
        )

        graph.add_conditional_edges(
            "answer_check",
            lambda s: route_after_answer_check(s, settings),
            {"finalize": "finalize", "transform_query": "transform_query", "force_exit": "force_exit"},
        )

        graph.add_edge("finalize", END)
        graph.add_edge("force_exit", END)

        self._graph_builder = graph

    def compile(
        self,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
    ):
        return self._graph_builder.compile(checkpointer=checkpointer, store=store)

    async def run(
        self,
        state: dict,
        thread_id: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
    ) -> dict[str, Any]:
        compiled = self.compile(checkpointer=checkpointer, store=store)
        config = {"configurable": {"thread_id": thread_id}} if thread_id else None
        result = await compiled.ainvoke(state, config)
        return cast(dict[str, Any], result)

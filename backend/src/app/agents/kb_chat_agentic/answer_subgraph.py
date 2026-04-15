"""KB Chat 答案生成子图。"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, StateGraph
from langgraph.types import RetryPolicy

from app.agents.kb_chat_trace_metadata import extend_kb_chat_node_metadata
from app.agents.kb_chat_trace_nodes import wrap_kb_chat_node_with_io
from app.agents.kb_chat_agentic_state import KbChatInternalState
from app.core.settings import Settings

from .answer_subgraph_finalize import (
    _answer_commit,
    _answer_repair,
    _draft_generate,
)
from .answer_subgraph_review_ops import (
    _answer_review,
    _answer_review_citation,
    _answer_review_dispatch,
    _answer_review_fuse,
)
from .answer_subgraph_shared import KbChatAnswerSubgraphContext

def build_answer_subgraph(
    *,
    settings: Settings,
    chat_model: BaseChatModel,
):
    """为父级 KB Chat 图构建已编译的答案子图。"""

    graph = StateGraph(
        state_schema=KbChatInternalState,
        context_schema=KbChatAnswerSubgraphContext,
    )
    generation_retry_policy = RetryPolicy(
        max_attempts=max(
            2, int(getattr(settings, "kb_chat_max_generation_retries", 2)) + 1
        )
    )

    def add_traced_node(
        node_id: str,
        node_callable: Any,
        *,
        side_effect_type: str,
        retry_policy: RetryPolicy | None = None,
        retry_disabled_reason: str | None = None,
        **kwargs: Any,
    ) -> None:
        metadata = extend_kb_chat_node_metadata(
            node_id,
            side_effect_type=side_effect_type,
            retry_enabled=retry_policy is not None,
        )
        if retry_policy is None:
            metadata["retry_disabled_reason"] = (
                retry_disabled_reason or side_effect_type
            )
        graph.add_node(
            node_id,
            wrap_kb_chat_node_with_io(node_id, node_callable),
            metadata=metadata,
            retry_policy=retry_policy,
            **kwargs,
        )

    add_traced_node(
        "draft_generate",
        lambda s, runtime: _draft_generate(
            s, runtime, settings=settings, chat_model=chat_model
        ),
        side_effect_type="llm",
        retry_policy=generation_retry_policy,
    )
    add_traced_node(
        "answer_review_dispatch",
        lambda s, runtime: _answer_review_dispatch(
            s,
            runtime,
            settings=settings,
        ),
        side_effect_type="deterministic_rule",
        retry_disabled_reason="parallel_fanout",
        destinations=(
            "answer_review_citation",
            "answer_review",
            "answer_review_fuse",
        ),
    )
    add_traced_node(
        "answer_review_citation",
        lambda s, runtime: _answer_review_citation(
            s,
            runtime,
            settings=settings,
            chat_model=chat_model,
        ),
        side_effect_type="llm",
        retry_policy=generation_retry_policy,
    )
    add_traced_node(
        "answer_review",
        lambda s, runtime: _answer_review(
            s, runtime, settings=settings, chat_model=chat_model
        ),
        side_effect_type="llm",
        retry_policy=generation_retry_policy,
    )
    add_traced_node(
        "answer_review_fuse",
        lambda s, runtime: _answer_review_fuse(
            s,
            runtime,
            settings=settings,
        ),
        side_effect_type="deterministic_rule",
        destinations=("answer_commit", "answer_repair"),
    )
    add_traced_node(
        "answer_repair",
        lambda s, runtime: _answer_repair(
            s, runtime, settings=settings, chat_model=chat_model
        ),
        side_effect_type="llm",
        retry_policy=generation_retry_policy,
    )
    add_traced_node(
        "answer_commit",
        lambda s, runtime: _answer_commit(s, runtime, settings=settings),
        side_effect_type="deterministic_rule",
        defer=True,
    )

    graph.set_entry_point("draft_generate")
    graph.add_edge("draft_generate", "answer_review_dispatch")
    graph.add_edge("answer_review_citation", "answer_review_fuse")
    graph.add_edge("answer_review", "answer_review_fuse")
    graph.add_edge("answer_repair", "answer_review_dispatch")
    graph.add_edge("answer_commit", END)
    return graph.compile(name="kb_chat_answer_subgraph")

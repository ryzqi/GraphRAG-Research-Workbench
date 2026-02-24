"""KB Chat agentic graph state (structured + checkpointer-friendly).

This change introduces a structured, serializable state schema that the upcoming
agentic KB Chat LangGraph will use.

Persistence rules (LangGraph checkpointing/store):
- Anything stored in the *graph state* must be serializable by LangGraph's default
  serializer (JsonPlusSerializer) when a checkpointer is enabled.
- Do NOT put runtime-only objects in state (DB sessions, HTTP clients, tools,
  callbacks, dataclass instances like RetrievalResult, etc.). Keep them in node
  closures / dependencies and write only primitives, dict/list, and LangChain/
  LangGraph primitives (e.g. AnyMessage) to state.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages

# -----------------------------
# Retrieval provenance & evidence
# -----------------------------

from app.schemas.query_enhancement import QueryHitSource, QueryItem


RetrievalStage = Literal["dense", "bm25", "rrf", "rerank"]


class RetrievalCandidate(TypedDict, total=False):
    """A single retrieval candidate (serializable).

    This is intentionally flat and JSON-friendly to ensure checkpointing works.
    """

    kb_id: str
    material_id: str
    chunk_id: str
    score: float
    stage: RetrievalStage

    excerpt: str
    locator: dict[str, Any] | None
    metadata: dict[str, Any] | None
    chunk_role: str | None
    parent_chunk_id: str | None

    # Provenance: which query(ies) hit this chunk.
    hits: list[QueryHitSource]


EvidenceSourceKind = Literal["kb", "external"]


class GraphEvidenceItem(TypedDict, total=False):
    """Chunk-level evidence item used by generation + auditing (serializable)."""

    source_kind: EvidenceSourceKind
    kb_id: str
    material_id: str
    chunk_id: str

    locator: dict[str, Any] | None
    excerpt: str
    score: float

    hits: list[QueryHitSource]


# -----------------------------
# Reflection / budget / metrics
# -----------------------------

ReflectionAction = Literal["none", "clarify", "transform_query", "generate", "force_exit"]


class ReflectionResult(TypedDict, total=False):
    """Outputs from reflection layer graders (serializable)."""

    relevance_passed: bool
    review_passed: bool
    action: ReflectionAction
    reason: str


class LoopCounts(TypedDict):
    """Loop counters used for budget control."""

    total_rounds: int
    retrieval_retries: int
    generation_retries: int


class MemoryKeys(TypedDict, total=False):
    """Namespacing keys used by store/checkpointer (all strings for portability)."""

    user_id: str
    thread_id: str
    kb_ids: list[str]


class KbChatRuntimeConfig(TypedDict, total=False):
    """Per-session runtime feature toggles for KB answer chain."""

    query_rewrite_enabled: bool
    ambiguity_check_enabled: bool
    hyde_enabled: bool
    hybrid_retrieval_enabled: bool
    rerank_enabled: bool
    retrieval_top_k: int
    retrieval_rerank_top_k: int
    retrieval_hybrid_ranker: Literal["rrf", "weighted"]
    retrieval_hybrid_dense_weight: float
    retrieval_hybrid_sparse_weight: float
    retrieval_hybrid_rrf_k: int
    retrieval_parent_max_parents: int
    retrieval_parent_max_children_per_parent: int
    retrieval_multiscale_per_window_top_k: int
    retrieval_multiscale_rrf_k: int
    retrieval_multiscale_max_documents: int
    retrieval_multiscale_max_chunks_per_document: int


class ContextTurn(TypedDict):
    """A recent dialogue turn for display/debugging."""

    role: Literal["user", "assistant"]
    text: str


class ContextFrame(TypedDict, total=False):
    """Structured context assembled before rewrite/retrieval."""

    summary_text: str
    recent_turns: list[ContextTurn]
    memory_snippet: str
    current_question: str


# -----------------------------
# Graph state schema
# -----------------------------

class KbChatAgenticStateBase(TypedDict):
    """Required fields for agentic KB chat runs."""

    # NOTE: LangGraph provides special reducers for message lists.
    messages: Annotated[list[AnyMessage], add_messages]

    # Raw user question (unmodified).
    user_input: str

    # Keep compatibility with existing streaming/service plumbing.
    pending_tool_calls: list[dict]

    # Budget / observability (kept compatible with existing AgentRun fields).
    loop_counts: LoopCounts
    stage_summaries: dict[str, Any]
    metrics: dict[str, Any]

    # Store/checkpointer namespace (values are JSON-friendly).
    memory_keys: MemoryKeys
    runtime_config: KbChatRuntimeConfig


class KbChatAgenticState(KbChatAgenticStateBase, total=False):
    """Optional fields populated across stages.

    Stage I/O (high-level, to keep implementation honest):
    - MergeContext: reads messages/user_input/memory_keys -> writes
      context_frame/rewrite_input_query/display_context/merged_context
    - CorefRewrite: reads rewrite_input_query -> writes coref_query
    - AmbiguityCheck: reads coref_query/normalized_query -> writes reflection/action (clarify)
    - NormalizeRewrite: reads coref_query -> writes normalized_query
    - ComplexityRouter: reads normalized_query -> writes query_strategy
    - Decomposition: reads normalized_query -> writes sub_queries
    - MultiQuery: reads normalized_query -> writes multi_queries
    - HyDE: reads normalized_query -> writes hyde_doc/hyde_docs
    - QueryBundle: reads query family -> writes query_items (flattened, for retrieval)
    - RetrievalLayer: reads query family -> writes retrieval_candidates (+ optional reranked_candidates)
    - ReflectionLayer: reads candidates/evidence -> writes reflection (+ optional rewritten query)
    - Generator: reads final_context/evidence -> writes draft_answer/final_answer
    """

    context_frame: ContextFrame
    rewrite_input_query: str
    display_context: str
    merged_context: str

    coref_query: str
    normalized_query: str
    query_strategy: Literal["direct", "decomposition", "multi_query"]

    sub_queries: list[str]
    multi_queries: list[str]
    hyde_doc: str
    hyde_docs: list[str]
    query_items: list[QueryItem]

    retrieval_candidates: list[RetrievalCandidate]
    reranked_candidates: list[RetrievalCandidate]
    evidence_items: list[GraphEvidenceItem]

    final_context: str
    draft_answer: str
    final_answer: str
    best_answer: str
    best_answer_meta: dict[str, Any]

    reflection: ReflectionResult


def make_initial_state(
    *,
    user_input: str,
    messages: list[AnyMessage] | None = None,
    memory_keys: MemoryKeys | None = None,
    runtime_config: KbChatRuntimeConfig | None = None,
) -> KbChatAgenticState:
    """Create a minimal, serializable initial state for an agentic KB chat run."""

    return {
        "messages": messages or [],
        "user_input": user_input,
        "pending_tool_calls": [],
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
        "stage_summaries": {},
        "metrics": {},
        "memory_keys": memory_keys or {},
        "runtime_config": runtime_config or {},
        # Pre-initialize list fields to reduce KeyError risk in early node work.
        "sub_queries": [],
        "multi_queries": [],
        "hyde_docs": [],
        "query_items": [],
        "retrieval_candidates": [],
        "reranked_candidates": [],
        "evidence_items": [],
    }

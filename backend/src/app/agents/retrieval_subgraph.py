"""Retrieval subgraph for KB Chat flowchart Stage 4."""

from __future__ import annotations

from collections import Counter
from functools import partial
import re
from typing import Any, TypedDict

from langchain.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.types import RetryPolicy

from app.agents.kb_chat_agentic.reflection import (
    dispatch_subqueries,
    kb_retrieve_context,
    merge_subquery_context,
    retrieve_subquery_context,
)
from app.agents.kb_chat_trace_nodes import (
    extend_kb_chat_node_metadata,
    wrap_kb_chat_node_with_io,
)
from app.agents.kb_chat_agentic_state import (
    CompressContextInput,
    KbChatInternalState,
    RetrievalBudgetPlanInput,
)
from app.core.settings import Settings
from app.utils.token_counter import count_tokens_approximately

_TERM_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9_]{2,}")
_EVIDENCE_BLOCK_RE = re.compile(
    r"^\[([^\[\]\n]{1,128})\]\s*(.*?)(?=^\[[^\[\]\n]{1,128}\]\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")
_GENERIC_QUERY_TERMS = {
    "什么",
    "为何",
    "为啥",
    "如何",
    "怎样",
    "怎么",
    "是否",
    "能否",
    "可以",
    "请问",
    "有关",
    "关于",
    "多少",
    "哪些",
    "使用",
}


class KbChatGraphContext(TypedDict, total=False):
    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def _resolve_query_count(state: dict[str, Any]) -> int:
    query_items = state.get("query_items")
    if not isinstance(query_items, list):
        return 1
    count = sum(
        1 for item in query_items if isinstance(item, dict) and str(item.get("query") or "").strip()
    )
    return max(1, count)


def _budget_by_complexity(complexity: str) -> tuple[int, int, int]:
    if complexity == "complex":
        return 15, 100, 30
    if complexity == "moderate":
        return 10, 50, 20
    return 5, 20, 10


def _retrieval_budget_plan(
    state: RetrievalBudgetPlanInput,
    settings: Settings,
) -> dict[str, Any]:
    complexity = str(state.get("complexity_level") or "simple")
    query_count = _resolve_query_count(state)
    per_query_top_k, global_candidates_limit, rerank_input_limit = _budget_by_complexity(
        complexity
    )
    reflection = state.get("reflection")
    failure_reason = (
        str(reflection.get("reason") or "").strip().lower()
        if isinstance(reflection, dict)
        else ""
    )
    if failure_reason in {"no_evidence", "insufficient", "low_overlap", "retry"}:
        per_query_top_k += 2
        global_candidates_limit += 12
        rerank_input_limit += 8
    elif failure_reason == "severe_conflict":
        per_query_top_k += 1
        global_candidates_limit += 16
        rerank_input_limit += 12
    elif failure_reason == "conflict_retry_exhausted":
        rerank_input_limit += 6

    loop_counts = state.get("loop_counts")
    retry_count = (
        int(loop_counts.get("retrieval_retries") or 0)
        if isinstance(loop_counts, dict)
        else 0
    )
    if retry_count > 0:
        per_query_top_k = per_query_top_k + retry_count
        global_candidates_limit = global_candidates_limit + retry_count * 10
        rerank_input_limit = rerank_input_limit + retry_count * 8

    max_top_k = int(settings.retrieval_max_top_k)
    per_query_top_k = max(1, min(per_query_top_k, max_top_k))
    rerank_input_limit = max(
        per_query_top_k,
        min(rerank_input_limit, max(global_candidates_limit, max_top_k * 4)),
    )
    global_candidates_limit = max(
        rerank_input_limit,
        min(global_candidates_limit, max_top_k * 6),
    )

    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    stage_summaries = {
        **stage_summaries,
        "retrieval_budget_plan": {
            "complexity": complexity,
            "query_count": query_count,
            "per_query_top_k": per_query_top_k,
            "global_candidates_limit": global_candidates_limit,
            "rerank_input_limit": rerank_input_limit,
            "failure_reason": failure_reason or None,
            "retry_count": retry_count,
        },
    }
    return {
        "retrieval_budget": {
            "per_query_top_k": per_query_top_k,
            "global_candidates_limit": global_candidates_limit,
            "rerank_input_limit": rerank_input_limit,
        },
        "stage_summaries": stage_summaries,
    }


def _resolve_query_text(state: dict[str, Any]) -> str:
    for key in ("normalized_query", "coref_query", "rewrite_input_query", "user_input"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_terms(text: str, *, drop_generic: bool = False) -> set[str]:
    terms: set[str] = set()
    for match in _TERM_RE.finditer(text or ""):
        token = match.group(0).strip().lower()
        if len(token) < 2:
            continue
        if not (drop_generic and token in _GENERIC_QUERY_TERMS):
            terms.add(token)
        cjk_only = "".join(ch for ch in token if "\u4e00" <= ch <= "\u9fff")
        if len(cjk_only) < 2:
            continue
        max_ngram = min(4, len(cjk_only))
        for size in range(2, max_ngram + 1):
            for start in range(0, len(cjk_only) - size + 1):
                candidate = cjk_only[start : start + size]
                if drop_generic and candidate in _GENERIC_QUERY_TERMS:
                    continue
                terms.add(candidate)
    return terms


def _split_evidence_blocks(context: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if not context:
        return blocks
    for index, match in enumerate(_EVIDENCE_BLOCK_RE.finditer(context.strip())):
        label = str(match.group(1) or "").strip()
        body = str(match.group(2) or "").strip()
        if not label or not body:
            continue
        raw = f"[{label}] {body}".strip()
        blocks.append(
            {
                "index": index,
                "label": f"[{label}]",
                "body": body,
                "raw": raw,
                "tokens": count_tokens_approximately(raw),
            }
        )
    return blocks


def _normalize_dedupe_key(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def _sentence_score(sentence: str, query_terms: set[str]) -> int:
    if not sentence.strip():
        return 0
    if not query_terms:
        return 1
    sentence_terms = _extract_terms(sentence)
    return len(query_terms & sentence_terms)


def _score_block_relevance(
    *,
    query_terms: set[str],
    block_terms: set[str],
    term_document_frequency: Counter[str],
) -> float:
    if not query_terms or not block_terms:
        return 0.0
    score = 0.0
    for term in query_terms & block_terms:
        score += min(4.0, float(len(term))) / float(max(1, term_document_frequency.get(term, 1)))
    return round(score, 4)


def _select_relevant_excerpt(body: str, query_terms: set[str], *, token_budget: int) -> str:
    sentences = [
        sentence.strip()
        for sentence in _SENTENCE_SPLIT_RE.split(body)
        if isinstance(sentence, str) and sentence.strip()
    ]
    if not sentences:
        return body.strip()

    ranked = sorted(
        enumerate(sentences),
        key=lambda row: (-_sentence_score(row[1], query_terms), row[0]),
    )
    selected_indices: list[int] = []
    for idx, sentence in ranked:
        if _sentence_score(sentence, query_terms) <= 0 and selected_indices:
            continue
        selected_indices.append(idx)
        ordered = [sentences[item] for item in sorted(set(selected_indices))]
        excerpt = " ".join(ordered).strip()
        if count_tokens_approximately(excerpt) >= token_budget:
            break

    if not selected_indices:
        selected_indices = [0]

    ordered = [sentences[item] for item in sorted(set(selected_indices))]
    excerpt = " ".join(ordered).strip()
    if count_tokens_approximately(excerpt) <= token_budget:
        return excerpt

    trimmed = ordered[:1]
    excerpt = trimmed[0]
    while count_tokens_approximately(excerpt) > token_budget and len(excerpt) > 64:
        excerpt = excerpt[: max(64, int(len(excerpt) * 0.85))].rstrip()
    return excerpt


def _compress_context(state: CompressContextInput) -> dict[str, Any]:
    final_context = str(state.get("final_context") or "").strip()
    if not final_context:
        final_context = "（未找到相关内容）"
    token_limit = 2500
    token_count = count_tokens_approximately(final_context)
    within_limit = token_count <= token_limit
    query_text = _resolve_query_text(state)
    query_terms = _extract_terms(query_text, drop_generic=True)
    if not query_terms:
        query_terms = _extract_terms(query_text)
    compressed = final_context
    deduped_block_count = 0
    dropped_block_count = 0
    retained_labels: list[str] = []

    blocks = _split_evidence_blocks(final_context)
    if blocks:
        deduped_blocks: list[dict[str, Any]] = []
        seen_bodies: set[str] = set()
        scored_rows: list[dict[str, Any]] = []
        block_term_sets: dict[int, set[str]] = {}
        for block in blocks:
            body_key = _normalize_dedupe_key(str(block.get("body") or ""))
            if body_key in seen_bodies:
                deduped_block_count += 1
                continue
            seen_bodies.add(body_key)
            deduped_blocks.append(block)
            block_index = int(block.get("index") or 0)
            block_terms = _extract_terms(str(block.get("body") or ""))
            block_term_sets[block_index] = block_terms
            scored_rows.append(
                {
                    "block": block,
                    "score": 0.0,
                    "index": block_index,
                }
            )

        term_document_frequency: Counter[str] = Counter()
        for terms in block_term_sets.values():
            for term in query_terms & terms:
                term_document_frequency[term] += 1
        for row in scored_rows:
            block_index = int(row["index"])
            row["score"] = _score_block_relevance(
                query_terms=query_terms,
                block_terms=block_term_sets.get(block_index, set()),
                term_document_frequency=term_document_frequency,
            )

        scored_rows.sort(key=lambda row: (-float(row["score"]), int(row["index"])))
        selected_parts: list[str] = []
        selected_scores = [float(row["score"]) for row in scored_rows]
        max_score = max(selected_scores, default=0.0)
        has_relevant_block = max_score > 0
        low_relevance_cutoff = max_score * 0.6 if has_relevant_block else 0.0
        for row in scored_rows:
            block = row["block"]
            score = float(row["score"])
            if has_relevant_block and score < low_relevance_cutoff:
                dropped_block_count += 1
                continue
            if within_limit:
                candidate = str(block["raw"]).strip()
            else:
                excerpt_budget = 480 if score > 0 else 220
                excerpt = _select_relevant_excerpt(
                    str(block.get("body") or ""),
                    query_terms,
                    token_budget=excerpt_budget,
                )
                candidate = f"{block['label']} {excerpt}".strip()
            next_candidate = "\n\n".join([*selected_parts, candidate]).strip()
            if (
                selected_parts
                and count_tokens_approximately(next_candidate) > token_limit
            ):
                dropped_block_count += 1
                continue
            selected_parts.append(candidate)
            retained_labels.append(str(block["label"]))

        if selected_parts:
            if (
                within_limit
                and deduped_block_count == 0
                and dropped_block_count == 0
                and len(selected_parts) == len(blocks)
            ):
                compressed = final_context
            else:
                compressed = "\n\n".join(selected_parts).strip()
        else:
            compressed = deduped_blocks[0]["raw"] if deduped_blocks else final_context

    truncated = count_tokens_approximately(compressed) < token_count
    if count_tokens_approximately(compressed) > token_limit:
        keep_ratio = max(0.1, token_limit / max(count_tokens_approximately(compressed), 1))
        keep_chars = max(512, int(len(compressed) * keep_ratio))
        compressed = compressed[:keep_chars].rstrip() + "\n\n（上下文已压缩）"
        truncated = True
    compressed_tokens = count_tokens_approximately(compressed)
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    stage_summaries = {
        **stage_summaries,
        "context_compress": {
            "token_limit": token_limit,
            "input_tokens": token_count,
            "output_tokens": compressed_tokens,
            "truncated": truncated,
            "deduped_block_count": deduped_block_count,
            "dropped_block_count": dropped_block_count,
            "retained_block_count": len(retained_labels),
            "selected_labels": retained_labels[:12],
        },
    }
    return {
        "compression_stats": {
            "token_limit": token_limit,
            "input_tokens": token_count,
            "output_tokens": compressed_tokens,
            "truncated": truncated,
            "deduped_block_count": deduped_block_count,
            "dropped_block_count": dropped_block_count,
            "retained_block_count": len(retained_labels),
            "selected_labels": retained_labels[:12],
        },
        "final_context": compressed,
        "stage_summaries": stage_summaries,
    }


def build_retrieval_subgraph(*, settings: Settings, kb_tool: BaseTool):
    """Compile retrieval subgraph aligned to flowchart Stage 4."""

    graph = StateGraph(
        state_schema=KbChatInternalState,
        context_schema=KbChatGraphContext,
    )
    retrieval_retry_policy = RetryPolicy(
        max_attempts=max(2, int(getattr(settings, "kb_chat_max_retrieval_retries", 2)) + 1)
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
            metadata["retry_disabled_reason"] = retry_disabled_reason or side_effect_type
        graph.add_node(
            node_id,
            wrap_kb_chat_node_with_io(node_id, node_callable),
            metadata=metadata,
            retry_policy=retry_policy,
            **kwargs,
        )

    add_traced_node(
        "retrieval_budget_plan",
        partial(_retrieval_budget_plan, settings=settings),
        side_effect_type="deterministic_rule",
    )
    add_traced_node(
        "dispatch_subqueries",
        partial(dispatch_subqueries, settings=settings),
        side_effect_type="deterministic_rule",
        destinations=("retrieve_subquery", "retrieve"),
    )
    add_traced_node(
        "retrieve_subquery",
        partial(retrieve_subquery_context, settings=settings, kb_tool=kb_tool),
        side_effect_type="external_io",
        retry_policy=retrieval_retry_policy,
    )
    add_traced_node(
        "merge_subquery_context",
        partial(merge_subquery_context, settings=settings),
        side_effect_type="deterministic_rule",
    )
    add_traced_node(
        "retrieve",
        partial(kb_retrieve_context, settings=settings, kb_tool=kb_tool),
        side_effect_type="external_io",
        retry_policy=retrieval_retry_policy,
    )
    add_traced_node("context_compress", _compress_context, side_effect_type="deterministic_rule")

    graph.set_entry_point("retrieval_budget_plan")
    graph.add_edge("retrieval_budget_plan", "dispatch_subqueries")
    graph.add_edge("retrieve_subquery", "merge_subquery_context")
    graph.add_edge("merge_subquery_context", "context_compress")
    graph.add_edge("retrieve", "context_compress")
    graph.add_edge("context_compress", END)
    return graph.compile(name="kb_chat_retrieval_subgraph")

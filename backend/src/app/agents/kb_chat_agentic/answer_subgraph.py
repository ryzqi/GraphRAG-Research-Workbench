"""KB Chat 答案生成子图。

该子图封装“草稿生成 → 审查 → 可选修复 → 提交”流程，
并通过写入 `reflection.action/reason` 与 `stage_summaries.answer_subgraph`
保持父图路由契约不变。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Literal, TypedDict

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, RetryPolicy, Send
from pydantic import ValidationError

from app.agents.kb_chat_trace_nodes import (
    extend_kb_chat_node_metadata,
    wrap_kb_chat_node_with_io,
)
from app.agents.kb_chat_agentic.reflection import (
    _build_answer_coverage_hint,
    _extract_question_entities,
    _extract_required_dimensions,
    _extract_required_term_map,
    generate_draft,
)
from app.agents.kb_chat_agentic.schemas import (
    AnswerParagraph,
    AnswerRenderMeta,
    AnswerReviewSubDecision,
)
from app.agents.kb_chat_agentic_state import (
    AnswerCommitInput,
    AnswerRepairInput,
    AnswerReviewCitationInput,
    AnswerReviewDispatchInput,
    AnswerReviewFuseInput,
    AnswerReviewInput,
    DraftGenerateInput,
    KbChatInternalState,
    merge_routing_decision,
)
from app.core.settings import Settings
from app.prompts import get_prompt_loader
from app.services.kb_answer_paragraphs import (
    normalize_answer_text_variants,
    prune_unsupported_auxiliary_claims,
    render_answer_paragraphs,
)
from app.services.evidence_guardrails import (
    extract_citation_label_occurrences,
    is_kb_refusal_answer,
    normalize_citation_label,
    resolve_kb_refusal_answer,
)
from app.services.kb_evidence import resolve_structured_evidence
from app.services.query_rewrite_service import coerce_structured_result_payload
from app.services.streaming import extract_answer_text

from .budget import now_iso

logger = logging.getLogger(__name__)

_REPAIRABLE_FAILURE_REASONS = {
    "missing_citations",
    "invalid_citations",
    "citation_mismatch",
    "unsupported_claims",
}
_EVIDENCE_LINE_RE = re.compile(r"^\[([^\[\]\n]{1,128})\]\s+", re.MULTILINE)
_INLINE_CITATION_RE = re.compile(r"\[([^\[\]\n]{1,128})\]|【([^【】\n]{1,128})】")
_REVIEW_CHECKS: tuple[Literal["citation", "answer"], ...] = (
    "citation",
    "answer",
)


class KbChatAnswerSubgraphContext(TypedDict, total=False):
    """从父图透传的类型化运行时上下文。"""

    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def _as_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _get_loop_counts(state: dict[str, Any]) -> dict[str, int]:
    raw = state.get("loop_counts")
    if not isinstance(raw, dict):
        return {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0}
    return {
        "total_rounds": int(raw.get("total_rounds") or 0),
        "retrieval_retries": int(raw.get("retrieval_retries") or 0),
        "generation_retries": int(raw.get("generation_retries") or 0),
    }


def _current_review_round(state: dict[str, Any]) -> int:
    loop_counts = _get_loop_counts(state)
    return max(int(loop_counts.get("generation_retries") or 0), 0)


def _resolve_answer_subgraph_next_step(
    state: AnswerCommitInput,
    *,
    settings: Settings,
) -> str:
    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}
    if reflection_obj.get("review_passed") is True:
        return "END"

    loop_counts = _get_loop_counts(state)
    max_total_rounds = int(getattr(settings, "kb_chat_max_total_rounds", 3))
    max_retrieval_retries = int(getattr(settings, "kb_chat_max_retrieval_retries", 2))
    if loop_counts["total_rounds"] >= max_total_rounds:
        return "force_exit"
    if loop_counts["retrieval_retries"] >= max_retrieval_retries:
        return "force_exit"
    return "transform_query"


def _merge_stage_summary(
    state: dict[str, Any],
    key: str,
    summary: dict[str, Any],
    *,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {}
    state_stage = state.get("stage_summaries")
    if isinstance(state_stage, dict):
        base = {**state_stage}
    if isinstance(updates, dict):
        updates_stage = updates.get("stage_summaries")
        if isinstance(updates_stage, dict):
            base = {**base, **updates_stage}
    return {"stage_summaries": {**base, key: summary}}


def _merge_subgraph_state(
    state: dict[str, Any],
    patch: dict[str, Any],
    *,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    current = state.get("answer_subgraph_state")
    if isinstance(current, dict):
        merged = {**current}
    if isinstance(updates, dict):
        in_updates = updates.get("answer_subgraph_state")
        if isinstance(in_updates, dict):
            merged = {**merged, **in_updates}
    return {"answer_subgraph_state": {**merged, **patch}}


def _resolve_query_text(state: dict[str, Any]) -> str:
    return _as_str(
        state.get("normalized_query")
        or state.get("resolved_query")
        or state.get("coref_query")
        or state.get("rewrite_input_query")
        or state.get("user_input")
    ).strip()


def _extract_evidence_labels(final_context: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    if not final_context:
        return labels
    for match in _EVIDENCE_LINE_RE.finditer(final_context):
        raw = _as_str(match.group(1)).strip()
        if not raw:
            continue
        normalized = f"[{raw}]"
        labels.setdefault(normalized.casefold(), normalized)
    return labels


def _resolve_allowed_citation_labels(
    state: dict[str, Any],
    *,
    final_context: str,
) -> tuple[dict[str, str], str, str]:
    evidence_items, citation_catalog, structured_context = resolve_structured_evidence(
        state.get("evidence_items"),
        citation_catalog=state.get("citation_catalog"),
    )
    if citation_catalog:
        labels = {
            f"[{citation_id}]".casefold(): f"[{citation_id}]"
            for citation_id in citation_catalog
        }
        return labels, "citation_catalog", structured_context or final_context
    return _extract_evidence_labels(final_context), "final_context", final_context


def _extract_citations(answer: str) -> list[str]:
    if not answer:
        return []
    return [f"[{label}]" for label in extract_citation_label_occurrences(answer)]


def _partition_citations(
    answer: str, *, allowed_labels: dict[str, str]
) -> tuple[list[str], set[str], set[str]]:
    if not answer:
        return [], set(), set()
    all_citations = _extract_citations(answer)
    valid: set[str] = set()
    invalid: set[str] = set()
    for label in all_citations:
        key = label.casefold()
        if key in allowed_labels:
            valid.add(allowed_labels[key])
        else:
            invalid.add(label)
    return all_citations, valid, invalid


def _normalize_citation_id(value: object) -> str:
    return normalize_citation_label(_as_str(value))


def _normalize_citation_label(value: object) -> str:
    citation_id = _normalize_citation_id(value)
    return f"[{citation_id}]" if citation_id else ""


def _ordered_unique_paragraph_ids(
    paragraphs: list[AnswerParagraph],
    paragraph_ids: set[str],
) -> list[str]:
    return [
        paragraph.paragraph_id
        for paragraph in paragraphs
        if paragraph.paragraph_id in paragraph_ids
    ]


def _load_answer_paragraphs(
    state: dict[str, Any],
    *,
    draft_answer: str = "",
) -> list[AnswerParagraph]:
    raw_paragraphs = state.get("answer_paragraphs")
    paragraphs: list[AnswerParagraph] = []
    if isinstance(raw_paragraphs, list):
        for raw in raw_paragraphs:
            try:
                paragraphs.append(AnswerParagraph.model_validate(raw))
            except ValidationError:
                continue
        return paragraphs
    if not draft_answer:
        return []
    fallback_citation_ids = [
        citation_id
        for citation_id in (
            _normalize_citation_id(raw_label)
            for raw_label in _extract_citations(draft_answer)
        )
        if citation_id
    ]
    try:
        return [
            AnswerParagraph(
                paragraph_id="p1",
                text=draft_answer,
                citation_ids=fallback_citation_ids,
                claims=[],
                review_status="passed",
            )
        ]
    except ValidationError:
        return []


def _resolve_unsupported_scope(
    paragraphs: list[AnswerParagraph],
) -> tuple[str, list[str]]:
    main_ids: set[str] = set()
    auxiliary_ids: set[str] = set()
    for paragraph in paragraphs:
        has_main_unsupported = any(
            claim.role == "main" and claim.support_status == "unsupported"
            for claim in paragraph.claims
        )
        has_auxiliary_unsupported = any(
            claim.role == "auxiliary" and claim.support_status == "unsupported"
            for claim in paragraph.claims
        )
        if has_main_unsupported:
            main_ids.add(paragraph.paragraph_id)
        if has_auxiliary_unsupported:
            auxiliary_ids.add(paragraph.paragraph_id)
    if main_ids and auxiliary_ids:
        scope = "mixed"
    elif main_ids:
        scope = "main"
    elif auxiliary_ids:
        scope = "auxiliary_only"
    else:
        scope = "none"
    return scope, _ordered_unique_paragraph_ids(paragraphs, main_ids | auxiliary_ids)


def _build_paragraph_review_counts(
    paragraphs: list[AnswerParagraph],
    *,
    failed_paragraph_ids: set[str],
) -> dict[str, int]:
    total = len(paragraphs)
    failed = min(len(failed_paragraph_ids), total)
    return {
        "total": total,
        "passed": max(total - failed, 0),
        "failed": failed,
    }


def _build_review_details(
    paragraphs: list[AnswerParagraph],
    *,
    failed_paragraph_ids: set[str],
    repair_target_ids: set[str] | None = None,
    unsupported_scope: str | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    repair_target_ids = repair_target_ids or set()
    details: dict[str, object] = {
        "paragraph_review_counts": _build_paragraph_review_counts(
            paragraphs,
            failed_paragraph_ids=failed_paragraph_ids,
        ),
        "repair_target_count": len(repair_target_ids),
        "unsupported_scope": unsupported_scope or "none",
    }
    if isinstance(extra, dict):
        details.update(extra)
    return details


def _build_answer_render_meta_from_paragraphs(
    paragraphs: list[AnswerParagraph],
) -> dict[str, Any]:
    citation_ids: list[str] = []
    claim_count = 0
    for paragraph in paragraphs:
        claim_count += len(paragraph.claims)
        citation_ids.extend(paragraph.citation_ids)
    return AnswerRenderMeta(
        paragraph_count=len(paragraphs),
        claim_count=claim_count,
        citation_count=len(dict.fromkeys(citation_ids)),
        citation_mode="paragraph_aggregate",
    ).model_dump()


def _normalize_repaired_paragraphs(
    paragraphs: list[AnswerParagraph],
) -> list[AnswerParagraph]:
    normalized: list[AnswerParagraph] = []
    for paragraph in paragraphs:
        has_unsupported = any(
            claim.support_status == "unsupported" for claim in paragraph.claims
        )
        review_status = "needs_repair" if has_unsupported else "passed"
        normalized.append(paragraph.model_copy(update={"review_status": review_status}))
    return normalized


def _format_paragraph_review_payload(paragraphs: list[AnswerParagraph]) -> str:
    if not paragraphs:
        return "（无可用段落元数据）"
    blocks: list[str] = []
    for paragraph in paragraphs:
        claim_lines = [
            (
                f"- role={claim.role}; support_status={claim.support_status}; "
                f"claim={claim.claim_text}; supporting_citation_ids={list(claim.supporting_citation_ids)}"
            )
            for claim in paragraph.claims
        ] or ["- （无 claims）"]
        blocks.append(
            "\n".join(
                [
                    f"paragraph_id={paragraph.paragraph_id}",
                    f"text={paragraph.text}",
                    f"citation_ids={list(paragraph.citation_ids)}",
                    "claims:",
                    *claim_lines,
                ]
            )
        )
    return "\n\n".join(blocks)


def _is_refusal_like_paragraph_text(text: str) -> bool:
    normalized = _as_str(text).strip()
    if not normalized:
        return False
    return is_kb_refusal_answer(normalized)


def _strip_inline_citations(text: str) -> str:
    if not text:
        return ""
    stripped = _INLINE_CITATION_RE.sub("", normalize_answer_text_variants(text))
    stripped = re.sub(r"[ \t]+\n", "\n", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip()


def _compact_answer_coverage_text(text: str) -> str:
    normalized = normalize_answer_text_variants(_strip_inline_citations(text))
    return re.sub(r"[\s\-‐‑‒–—―_]+", "", normalized).casefold()


def _detect_multi_entity_answer_gap(
    *,
    question: str,
    draft: str,
    paragraphs: list[AnswerParagraph],
) -> dict[str, object] | None:
    entities = _extract_question_entities(question)
    if len(entities) < 2:
        return None

    answer_body = "\n".join(
        paragraph.text.strip()
        for paragraph in paragraphs
        if paragraph.text and paragraph.text.strip()
    ).strip()
    if not answer_body:
        answer_body = draft
    compact_answer = _compact_answer_coverage_text(answer_body)
    missing_entities = [
        entity
        for entity in entities
        if _compact_answer_coverage_text(entity) not in compact_answer
    ]
    if not missing_entities:
        return None

    paragraph_ids = [
        paragraph.paragraph_id
        for paragraph in paragraphs
        if isinstance(paragraph.paragraph_id, str) and paragraph.paragraph_id.strip()
    ]
    return {
        "reason": "incomplete",
        "missing_entities": missing_entities,
        "required_dimensions": _extract_required_dimensions(question),
        "affected_paragraph_ids": paragraph_ids[-1:] if paragraph_ids else [],
        "coverage_guardrail": "multi_entity_entities",
    }


def _detect_required_original_term_gap(
    *,
    question: str,
    draft: str,
    paragraphs: list[AnswerParagraph],
    final_context: str,
) -> dict[str, object] | None:
    normalized_question = _as_str(question).strip()
    if not normalized_question or not final_context:
        return None

    required_dimensions = _extract_required_dimensions(normalized_question)
    requires_original_terms = any(
        dimension in required_dimensions for dimension in ("职责", "技术架构")
    ) or any(
        keyword in normalized_question
        for keyword in ("模型名称", "组件名称", "术语", "名词清单")
    )
    if not requires_original_terms:
        return None

    entities = _extract_question_entities(normalized_question)
    if len(entities) < 2:
        return None

    required_term_map = _extract_required_term_map(
        entities,
        final_context=final_context,
        required_dimensions=required_dimensions,
    )
    if not required_term_map:
        return None

    answer_body = "\n".join(
        paragraph.text.strip()
        for paragraph in paragraphs
        if paragraph.text and paragraph.text.strip()
    ).strip()
    if not answer_body:
        answer_body = draft
    compact_answer = _compact_answer_coverage_text(answer_body)
    if not compact_answer:
        return None

    missing_terms: dict[str, list[str]] = {}
    affected_ids: list[str] = []
    for entity in entities:
        compact_entity = _compact_answer_coverage_text(entity)
        if not compact_entity or compact_entity not in compact_answer:
            continue
        terms = required_term_map.get(entity) or []
        missing_for_entity = [
            term
            for term in terms
            if _compact_answer_coverage_text(term) not in compact_answer
        ]
        if not missing_for_entity:
            continue
        missing_terms[entity] = missing_for_entity
        for paragraph in paragraphs:
            paragraph_id = _as_str(paragraph.paragraph_id).strip()
            if not paragraph_id:
                continue
            compact_paragraph = _compact_answer_coverage_text(paragraph.text)
            if compact_entity in compact_paragraph:
                affected_ids.append(paragraph_id)

    if not missing_terms:
        return None

    ordered_affected_ids = list(dict.fromkeys(affected_ids))
    if not ordered_affected_ids:
        ordered_affected_ids = [
            paragraph.paragraph_id
            for paragraph in paragraphs
            if isinstance(paragraph.paragraph_id, str)
            and paragraph.paragraph_id.strip()
        ][-1:]

    return {
        "reason": "incomplete",
        "missing_terms": missing_terms,
        "required_dimensions": required_dimensions,
        "affected_paragraph_ids": ordered_affected_ids,
        "repair_target_count": len(ordered_affected_ids),
        "coverage_guardrail": "required_original_terms",
    }


def _project_answer_text_to_paragraphs(answer: str) -> list[AnswerParagraph]:
    cleaned_answer = normalize_answer_text_variants(_as_str(answer)).strip()
    if not cleaned_answer:
        return []
    raw_blocks = [
        block.strip() for block in re.split(r"\n\s*\n", cleaned_answer) if block.strip()
    ]
    if not raw_blocks:
        raw_blocks = [cleaned_answer]
    paragraphs: list[AnswerParagraph] = []
    for index, block in enumerate(raw_blocks, start=1):
        citation_ids = [
            citation_id
            for citation_id in (
                _normalize_citation_id(raw_label)
                for raw_label in _extract_citations(block)
            )
            if citation_id
        ]
        paragraphs.append(
            AnswerParagraph(
                paragraph_id=f"p{index}",
                text=_strip_inline_citations(block),
                citation_ids=list(dict.fromkeys(citation_ids)),
                claims=[],
                review_status="passed",
            )
        )
    return paragraphs


def _review_paragraph_citations(
    paragraphs: list[AnswerParagraph],
    *,
    allowed_labels: dict[str, str],
) -> dict[str, object]:
    allowed_by_id = {
        _normalize_citation_id(label).casefold(): label
        for label in allowed_labels.values()
        if _normalize_citation_id(label)
    }
    all_citations: list[str] = []
    valid_citations: set[str] = set()
    invalid_citations: set[str] = set()
    missing_citations: list[str] = []
    citation_mismatches: list[str] = []
    failed_ids: set[str] = set()
    metadata_incomplete = False

    for paragraph in paragraphs:
        paragraph_valid_labels: set[str] = set()
        paragraph_has_citations = False
        for raw_citation_id in paragraph.citation_ids:
            normalized_id = _normalize_citation_id(raw_citation_id)
            if not normalized_id:
                continue
            paragraph_has_citations = True
            label = f"[{normalized_id}]"
            all_citations.append(label)
            canonical = allowed_by_id.get(normalized_id.casefold())
            if canonical is None:
                invalid_citations.add(label)
                failed_ids.add(paragraph.paragraph_id)
            else:
                valid_citations.add(canonical)
                paragraph_valid_labels.add(canonical)

        main_claims = [
            claim
            for claim in paragraph.claims
            if claim.role == "main" and claim.claim_text.strip()
        ]
        if (
            paragraph.text.strip()
            and not paragraph_has_citations
            and not main_claims
            and not _is_refusal_like_paragraph_text(paragraph.text)
        ):
            missing_citations.append(paragraph.text.strip())
            failed_ids.add(paragraph.paragraph_id)
            continue
        citable_main_claims = []
        for claim in main_claims:
            supporting_labels = {
                normalized
                for normalized in (
                    _normalize_citation_label(raw_support_id)
                    for raw_support_id in claim.supporting_citation_ids
                )
                if normalized
            }
            if (
                claim.support_status in {"supported", "weak_supported"}
                and supporting_labels
            ):
                citable_main_claims.append((claim, supporting_labels))
        if not main_claims and paragraph.text.strip() and paragraph_has_citations:
            metadata_incomplete = True
        if not paragraph_has_citations and citable_main_claims:
            for claim, _ in citable_main_claims:
                missing_citations.append(claim.claim_text)
            failed_ids.add(paragraph.paragraph_id)
            continue
        for claim, supporting_labels in citable_main_claims:
            if not paragraph_has_citations:
                missing_citations.append(claim.claim_text)
                failed_ids.add(paragraph.paragraph_id)
                continue
            if not supporting_labels.issubset(paragraph_valid_labels):
                citation_mismatches.append(claim.claim_text)
                failed_ids.add(paragraph.paragraph_id)
        if main_claims and not citable_main_claims and paragraph_has_citations:
            metadata_incomplete = True

    unsupported_scope, _ = _resolve_unsupported_scope(paragraphs)
    if invalid_citations:
        reason = "invalid_citations"
        passed = False
    elif missing_citations:
        reason = "missing_citations"
        passed = False
    elif citation_mismatches:
        reason = "citation_mismatch"
        passed = False
    else:
        reason = "passed"
        passed = True

    affected_ids = _ordered_unique_paragraph_ids(paragraphs, failed_ids)
    repair_target_ids = set(affected_ids) if not passed else set()
    return {
        "passed": passed,
        "reason": reason,
        "all_citations": all_citations,
        "valid_citations": valid_citations,
        "invalid_citations": invalid_citations,
        "missing_citations": list(dict.fromkeys(missing_citations))[:3],
        "citation_mismatches": list(dict.fromkeys(citation_mismatches))[:3],
        "affected_paragraph_ids": affected_ids,
        "needs_llm": bool(paragraphs) and passed and metadata_incomplete,
        "details": _build_review_details(
            paragraphs,
            failed_paragraph_ids=failed_ids,
            repair_target_ids=repair_target_ids,
            unsupported_scope=unsupported_scope,
            extra={
                "invalid_citation_count": len(invalid_citations),
                "missing_citation_count": len(list(dict.fromkeys(missing_citations))),
                "citation_mismatch_count": len(
                    list(dict.fromkeys(citation_mismatches))
                ),
            },
        ),
    }


def _resolve_answer_review_details(
    paragraphs: list[AnswerParagraph],
    *,
    reason: str,
    unsupported_claims: list[str],
) -> tuple[list[str], dict[str, object]]:
    unsupported_scope, unsupported_ids = _resolve_unsupported_scope(paragraphs)
    failed_ids: set[str] = {
        paragraph.paragraph_id
        for paragraph in paragraphs
        if paragraph.review_status != "passed"
        or any(claim.support_status == "unsupported" for claim in paragraph.claims)
    }
    affected_ids = unsupported_ids if reason == "unsupported_claims" else []
    repair_target_ids = (
        set(unsupported_ids) if unsupported_scope == "auxiliary_only" else set()
    )
    details = _build_review_details(
        paragraphs,
        failed_paragraph_ids=failed_ids,
        repair_target_ids=repair_target_ids,
        unsupported_scope=unsupported_scope,
        extra={"unsupported_claim_count": len(unsupported_claims)},
    )
    return affected_ids, details


def _extract_run_details(run: dict[str, Any]) -> dict[str, Any]:
    raw = run.get("details")
    return raw if isinstance(raw, dict) else {}


def _extract_run_affected_paragraph_ids(run: dict[str, Any]) -> set[str]:
    raw = run.get("affected_paragraph_ids")
    if not isinstance(raw, list):
        return set()
    return {
        _as_str(paragraph_id).strip()
        for paragraph_id in raw
        if _as_str(paragraph_id).strip()
    }


def _coalesce_paragraph_summary(
    citation: dict[str, Any],
    answer: dict[str, Any],
) -> tuple[dict[str, int], int, str]:
    answer_details = _extract_run_details(answer)
    citation_details = _extract_run_details(citation)

    def _counts_from(details: dict[str, Any]) -> dict[str, int]:
        raw = details.get("paragraph_review_counts")
        if not isinstance(raw, dict):
            return {"total": 0, "passed": 0, "failed": 0}
        return {
            "total": int(raw.get("total") or 0),
            "passed": int(raw.get("passed") or 0),
            "failed": int(raw.get("failed") or 0),
        }

    answer_counts = _counts_from(answer_details)
    citation_counts = _counts_from(citation_details)
    affected_ids = _extract_run_affected_paragraph_ids(
        citation
    ) | _extract_run_affected_paragraph_ids(answer)
    total = max(answer_counts["total"], citation_counts["total"], len(affected_ids))
    failed = max(answer_counts["failed"], citation_counts["failed"], len(affected_ids))
    counts = {
        "total": total,
        "passed": max(total - failed, 0),
        "failed": failed,
    }
    repair_target_count = max(
        int(answer_details.get("repair_target_count") or 0),
        int(citation_details.get("repair_target_count") or 0),
    )
    unsupported_scope_summary = (
        _as_str(
            answer_details.get(
                "unsupported_scope",
                citation_details.get("unsupported_scope", "none"),
            )
        ).strip()
        or "none"
    )
    return counts, repair_target_count, unsupported_scope_summary


def _is_repairable_review_failure(
    *,
    reason: str,
    citation: dict[str, Any],
    answer: dict[str, Any],
) -> bool:
    if reason == "incomplete":
        coverage_guardrail = _as_str(
            _extract_run_details(answer).get("coverage_guardrail")
        ).strip()
        return coverage_guardrail == "required_original_terms"
    if reason not in _REPAIRABLE_FAILURE_REASONS:
        return False
    if reason != "unsupported_claims":
        return True
    unsupported_scope = _as_str(
        _extract_run_details(answer).get("unsupported_scope")
    ).strip()
    return unsupported_scope == "auxiliary_only"


def _resolve_answer_review_details_from_state(state: dict[str, Any]) -> dict[str, Any]:
    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}
    review_breakdown = (
        reflection_obj.get("review_breakdown")
        if isinstance(reflection_obj.get("review_breakdown"), dict)
        else {}
    )
    answer_check = (
        review_breakdown.get("answer")
        if isinstance(review_breakdown.get("answer"), dict)
        else {}
    )
    details = answer_check.get("details")
    if isinstance(details, dict):
        return details
    return {}


def _resolve_unsupported_scope_from_state(state: dict[str, Any]) -> str:
    review_details = _resolve_answer_review_details_from_state(state)
    unsupported_scope = _as_str(review_details.get("unsupported_scope")).strip()
    if unsupported_scope:
        return unsupported_scope

    stage_summaries = state.get("stage_summaries")
    answer_review_summary = (
        stage_summaries.get("answer_review")
        if isinstance(stage_summaries, dict)
        and isinstance(stage_summaries.get("answer_review"), dict)
        else {}
    )
    return _as_str(answer_review_summary.get("unsupported_scope_summary")).strip()


def _count_unsupported_auxiliary_claims(paragraphs: list[AnswerParagraph]) -> int:
    return sum(
        1
        for paragraph in paragraphs
        for claim in paragraph.claims
        if claim.role == "auxiliary" and claim.support_status == "unsupported"
    )


def _maybe_repair_auxiliary_only_paragraphs(
    state: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], str] | None:
    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}
    reason = _as_str(reflection_obj.get("reason")).strip()
    if reason != "unsupported_claims":
        return None

    unsupported_scope = _resolve_unsupported_scope_from_state(state)
    if unsupported_scope != "auxiliary_only":
        return None

    paragraphs = _load_answer_paragraphs(
        state,
        draft_answer=_as_str(state.get("draft_answer")).strip(),
    )
    if not paragraphs:
        return None

    pruned = prune_unsupported_auxiliary_claims(paragraphs)
    normalized = _normalize_repaired_paragraphs(pruned)
    serialized = [paragraph.model_dump() for paragraph in normalized]
    render_meta = _build_answer_render_meta_from_paragraphs(normalized)
    repaired_answer = render_answer_paragraphs(normalized)
    return serialized, render_meta, repaired_answer


def _project_repair_candidate(
    candidate: str,
    *,
    allowed_labels: dict[str, str],
) -> tuple[
    list[dict[str, Any]] | None,
    dict[str, Any] | None,
    str | None,
    str | None,
]:
    projected_paragraphs = _project_answer_text_to_paragraphs(candidate)
    if not projected_paragraphs:
        return None, None, None, "repair_projection_empty"

    paragraph_review = _review_paragraph_citations(
        projected_paragraphs,
        allowed_labels=allowed_labels,
    )
    review_reason = _as_str(paragraph_review.get("reason")).strip()
    if review_reason != "passed":
        return None, None, None, f"repair_projection_{review_reason or 'failed'}"

    normalized_answer = render_answer_paragraphs(projected_paragraphs)
    if not normalized_answer:
        return None, None, None, "repair_projection_empty"

    return (
        [paragraph.model_dump() for paragraph in projected_paragraphs],
        _build_answer_render_meta_from_paragraphs(projected_paragraphs),
        normalized_answer,
        "",
    )


def _classify_structured_error(exc: Exception) -> str:
    name = exc.__class__.__name__
    if name == "StructuredOutputValidationError":
        return "invalid_schema"
    if name == "MultipleStructuredOutputsError":
        return "multiple_structured_outputs"
    return "error"


async def _judge_structured(
    *,
    chat_model: BaseChatModel,
    system: str,
    user: str,
) -> tuple[AnswerReviewSubDecision | None, str | None]:
    try:
        structured_model = chat_model.with_structured_output(
            AnswerReviewSubDecision,
            method="function_calling",
            include_raw=True,
        )
        result = await structured_model.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return None, _classify_structured_error(exc)
    payload, reason = coerce_structured_result_payload(
        result=result,
        schema=AnswerReviewSubDecision,
    )
    if payload is None:
        return None, reason
    if isinstance(payload, AnswerReviewSubDecision):
        return payload, None
    try:
        payload = AnswerReviewSubDecision.model_validate(payload)
    except ValidationError:
        return None, "invalid_schema"
    return payload, None


def _resolve_subcheck(
    state: AnswerReviewFuseInput,
    check: str,
) -> dict[str, Any] | None:
    active_round = _current_review_round(state)
    runs = state.get("answer_review_runs")
    if not isinstance(runs, list):
        return None
    for run in reversed(runs):
        if not isinstance(run, dict):
            continue
        if _as_str(run.get("check")) != check:
            continue
        run_round = run.get("review_round")
        if isinstance(run_round, int):
            if run_round == active_round:
                return run
            continue
        if active_round == 0:
            return run
    return None


async def _answer_review_dispatch(
    state: AnswerReviewDispatchInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
) -> Command[str]:
    _ = runtime, settings
    review_round = _current_review_round(state)
    send_tasks: list[Send] = [
        Send(
            "answer_review_citation",
            {
                **state,
                "answer_review_task": {
                    "check": "citation",
                    "review_round": review_round,
                },
            },
        ),
        Send(
            "answer_review",
            {
                **state,
                "answer_review_task": {
                    "check": "answer",
                    "review_round": review_round,
                },
            },
        ),
    ]
    return Command(
        update={
            **_merge_subgraph_state(
                state,
                {"phase": "answer_review_dispatch", "last_updated_at": now_iso()},
            ),
            **_merge_stage_summary(
                state,
                "answer_review_dispatch",
                {
                    "review_round": review_round,
                    "check_count": len(send_tasks),
                    "checks": list(_REVIEW_CHECKS),
                    "latency_ms": 0,
                    "completed_at": now_iso(),
                },
            ),
        },
        goto=send_tasks,
    )


def _emit_review_event(payload: dict[str, Any]) -> None:
    writer = None
    try:
        writer = get_stream_writer()
    except Exception:
        writer = None
    if callable(writer):
        writer(payload)


async def _answer_review_citation(
    state: AnswerReviewCitationInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: BaseChatModel | None = None,
) -> dict[str, Any]:
    _ = settings
    start = time.perf_counter()
    review_round = _current_review_round(state)
    draft = _as_str(state.get("draft_answer")).strip()
    raw_final_context = _as_str(state.get("final_context")).strip()
    question = _resolve_query_text(state)
    evidence_labels, label_source, final_context = _resolve_allowed_citation_labels(
        state,
        final_context=raw_final_context,
    )
    paragraphs = _load_answer_paragraphs(state, draft_answer=draft)
    paragraph_review = _review_paragraph_citations(
        paragraphs,
        allowed_labels=evidence_labels,
    )
    all_citations = paragraph_review["all_citations"]
    valid_citations = paragraph_review["valid_citations"]
    invalid_citations = paragraph_review["invalid_citations"]
    missing_citations = paragraph_review["missing_citations"]
    citation_mismatches = paragraph_review["citation_mismatches"]
    affected_paragraph_ids = paragraph_review["affected_paragraph_ids"]
    details = paragraph_review["details"]
    fallback_reason: str | None = None
    decision_source = "rule"
    if not draft:
        passed = False
        reason = "non_answer"
        confidence = 0.9
    elif not evidence_labels:
        passed = False
        reason = "no_evidence"
        confidence = 0.9
    elif isinstance(state.get("answer_paragraphs"), list) and not paragraphs:
        passed = True
        reason = "passed"
        confidence = 1.0
        missing_citations = []
    elif paragraph_review["reason"] != "passed":
        passed = bool(paragraph_review["passed"])
        reason = _as_str(paragraph_review["reason"]).strip() or "missing_citations"
        confidence = 0.9
        if reason == "citation_mismatch":
            missing_citations = citation_mismatches
    elif bool(paragraph_review["needs_llm"]):
        review_model = chat_model or getattr(runtime, "chat_model", None)
        prompts = get_prompt_loader()
        try:
            system_prompt = prompts.render_with_few_shot("kb_chat/citation_review")
        except KeyError:
            system_prompt = (
                "你是严格的知识库段落级引用来源审查器。"
                "请基于段落、claim 与 citation_ids 判断主断言的来源是否完整且对齐。"
                '仅输出 JSON：{"passed": true/false, "reason": "passed|missing_citations|citation_mismatch", "confidence": 0-1, "missing_citations": [], "unsupported_claims": [], "affected_paragraph_ids": [], "details": {}}。'
            )
        if review_model is None:
            judge = None
            fallback_reason = "missing_chat_model"
        else:
            judge, fallback_reason = await _judge_structured(
                chat_model=review_model,
                system=system_prompt,
                user=(
                    f"问题：{question}\n\n"
                    f"参考内容：\n{final_context}\n\n"
                    f"回答：\n{draft}\n\n"
                    "段落级审查数据：\n"
                    f"{_format_paragraph_review_payload(paragraphs)}"
                ),
            )
        if isinstance(judge, AnswerReviewSubDecision):
            passed = bool(judge.passed)
            reason = judge.reason
            confidence = max(0.0, min(1.0, float(judge.confidence)))
            decision_source = "llm"
            missing_citations = (
                [] if passed else (judge.missing_citations or missing_citations)
            )
            affected_paragraph_ids = list(
                judge.affected_paragraph_ids or affected_paragraph_ids
            )
            if isinstance(judge.details, dict) and judge.details:
                details = dict(judge.details)
        else:
            passed = (
                _as_str(getattr(settings, "kb_chat_grader_fail_policy", "closed"))
                .strip()
                .lower()
                == "open"
            )
            reason = "passed" if passed else "missing_citations"
            confidence = 0.0
            decision_source = "fallback"
            missing_citations = [] if passed else missing_citations
    else:
        passed = True
        reason = "passed"
        confidence = 1.0
        missing_citations = []
    result = {
        "review_round": review_round,
        "check": "citation",
        "passed": passed,
        "reason": reason,
        "confidence": confidence,
        "details": details,
        "affected_paragraph_ids": affected_paragraph_ids,
        "fallback_reason": fallback_reason,
        "decision_source": decision_source,
        "label_source": label_source,
        "citation_count": len(all_citations),
        "valid_citation_count": len(valid_citations),
        "available_citation_labels": sorted(evidence_labels.values()),
        "invalid_citations": sorted(invalid_citations),
        "missing_citations": missing_citations,
        "latency_ms": int((time.perf_counter() - start) * 1000),
    }
    _emit_review_event(
        {
            "event_type": "answer_review_subcheck",
            "check": "citation",
            "passed": passed,
            "reason": reason,
            "ts": now_iso(),
        }
    )
    return {"answer_review_runs": [result]}


async def _answer_review_llm_check(
    state: AnswerReviewInput,
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    start = time.perf_counter()
    review_round = _current_review_round(state)
    question = _resolve_query_text(state)
    raw_final_context = _as_str(state.get("final_context")).strip()
    _, _, final_context = _resolve_allowed_citation_labels(
        state,
        final_context=raw_final_context,
    )
    draft = _as_str(state.get("draft_answer")).strip()
    paragraphs = _load_answer_paragraphs(state, draft_answer=draft)
    fallback_reason: str | None = None
    prompt_key = "kb_chat/answer_review"
    default_system = (
        "你是严格的知识库答案有效性审查器。"
        "请同时判断回答是否直接回应问题，以及主断言与辅助断言分别是否被参考内容支持。"
        '仅输出 JSON：{"passed": true/false, "reason": "...", "confidence": 0-1, "missing_citations": [], "unsupported_claims": [], "affected_paragraph_ids": [], "details": {}}。'
    )
    prompts = get_prompt_loader()
    try:
        system_prompt = prompts.render_with_few_shot(prompt_key)
    except KeyError:
        system_prompt = default_system
    coverage_hint = _build_answer_coverage_hint(question, final_context)
    coverage_block = f"{coverage_hint}\n\n" if coverage_hint else ""
    judge, fallback_reason = await _judge_structured(
        chat_model=chat_model,
        system=system_prompt,
        user=(
            f"问题：{question}\n\n"
            f"{coverage_block}"
            f"参考内容：\n{final_context}"
            f"\n\n回答：\n{draft}\n\n段落级审查数据：\n{_format_paragraph_review_payload(paragraphs)}"
        ),
    )
    if isinstance(judge, AnswerReviewSubDecision):
        passed = bool(judge.passed)
        reason = judge.reason
        confidence = float(judge.confidence)
        decision_source = "llm"
        unsupported_claims = list(judge.unsupported_claims)
        missing_citations = list(judge.missing_citations)
    else:
        passed = settings.kb_chat_grader_fail_policy == "open"
        reason = "fallback_open" if passed else "fallback_closed"
        confidence = 0.0
        decision_source = "fallback"
        unsupported_claims = []
        missing_citations = []
    coverage_gap = _detect_multi_entity_answer_gap(
        question=question,
        draft=draft,
        paragraphs=paragraphs,
    )
    if coverage_gap is None:
        coverage_gap = _detect_required_original_term_gap(
            question=question,
            draft=draft,
            paragraphs=paragraphs,
            final_context=final_context,
        )
    if passed and coverage_gap is not None:
        passed = False
        reason = str(coverage_gap.get("reason") or "incomplete")
        confidence = min(confidence, 0.35)
        decision_source = "deterministic_guard"
    affected_paragraph_ids, details = _resolve_answer_review_details(
        paragraphs,
        reason=reason,
        unsupported_claims=unsupported_claims,
    )
    if coverage_gap is not None:
        guard_details = {
            "coverage_guardrail": coverage_gap.get("coverage_guardrail"),
            "missing_entities": coverage_gap.get("missing_entities") or [],
            "missing_terms": coverage_gap.get("missing_terms") or {},
            "required_dimensions": coverage_gap.get("required_dimensions") or [],
            "repair_target_count": int(coverage_gap.get("repair_target_count") or 0),
        }
        details = {
            **details,
            **guard_details,
        }
        guard_affected_ids = coverage_gap.get("affected_paragraph_ids")
        if (
            isinstance(guard_affected_ids, list)
            and guard_affected_ids
            and not affected_paragraph_ids
        ):
            affected_paragraph_ids = [
                _as_str(paragraph_id).strip()
                for paragraph_id in guard_affected_ids
                if _as_str(paragraph_id).strip()
            ]
    if isinstance(judge, AnswerReviewSubDecision):
        if judge.affected_paragraph_ids:
            affected_paragraph_ids = list(judge.affected_paragraph_ids)
        if isinstance(judge.details, dict) and judge.details:
            details = {
                **details,
                **judge.details,
            }
    result = {
        "review_round": review_round,
        "check": "answer",
        "passed": passed,
        "reason": reason,
        "confidence": max(0.0, min(1.0, confidence)),
        "unsupported_claims": unsupported_claims,
        "missing_citations": missing_citations,
        "affected_paragraph_ids": affected_paragraph_ids,
        "details": details,
        "fallback_reason": fallback_reason,
        "decision_source": decision_source,
        "latency_ms": int((time.perf_counter() - start) * 1000),
    }
    _emit_review_event(
        {
            "event_type": "answer_review_subcheck",
            "check": "answer",
            "passed": passed,
            "reason": reason,
            "fallback_reason": fallback_reason,
            "ts": now_iso(),
        }
    )
    return {"answer_review_runs": [result]}


async def _answer_review(
    state: AnswerReviewInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    _ = runtime
    return await _answer_review_llm_check(
        state, settings=settings, chat_model=chat_model
    )


async def _answer_review_fuse(
    state: AnswerReviewFuseInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
) -> Command[str]:
    _ = runtime
    start = time.perf_counter()
    review_round = _current_review_round(state)
    loop_counts = _get_loop_counts(state)
    loop_counts_updates = {**loop_counts}
    by_check = {
        check: (
            _resolve_subcheck(state, check)
            or {
                "review_round": review_round,
                "check": check,
                "passed": False,
                "reason": "fallback_closed",
            }
        )
        for check in _REVIEW_CHECKS
    }
    citation = by_check["citation"]
    answer = by_check["answer"]
    checks = [citation, answer]
    passed = all(bool(item.get("passed")) for item in checks)
    reason = "passed"
    if not passed:
        for key in ("citation", "answer"):
            current = by_check[key]
            if not bool(current.get("passed")):
                reason = _as_str(current.get("reason")).strip() or "fallback_closed"
                break
    avg_confidence = sum(float(item.get("confidence") or 0.0) for item in checks) / max(
        1, len(checks)
    )
    fallback_reason = next(
        (
            _as_str(item.get("fallback_reason")).strip()
            for item in checks
            if _as_str(item.get("fallback_reason")).strip()
        ),
        None,
    )
    decision_sources = {
        _as_str(item.get("decision_source")).strip()
        for item in checks
        if _as_str(item.get("decision_source")).strip()
    }
    if not passed:
        review_risk_level = "high"
    elif avg_confidence >= 0.8:
        review_risk_level = "low"
    else:
        review_risk_level = "medium"
    action = "none" if passed else "transform_query"
    draft = _as_str(state.get("draft_answer")).strip()
    paragraph_review_counts, repair_target_count, unsupported_scope_summary = (
        _coalesce_paragraph_summary(citation, answer)
    )
    best_answer_meta: dict[str, Any] | None = None
    if passed and draft:
        best_answer_meta = {
            "from_node": "answer_review_fuse",
            "reason": reason,
            "retrieval_round": max(loop_counts.get("retrieval_retries", 0), 0),
            "total_rounds": loop_counts_updates.get("total_rounds", 0),
            "completed_at": now_iso(),
        }
    stage_summary = {
        "review_round": review_round,
        "passed": passed,
        "reason": reason,
        "fallback_reason": fallback_reason,
        "fallback_used": fallback_reason is not None,
        "review_breakdown": by_check,
        "review_risk_level": review_risk_level,
        "review_confidence": round(max(0.0, min(1.0, avg_confidence)), 4),
        "review_decision_source": "mixed"
        if len(decision_sources) > 1
        else (next(iter(decision_sources)) if decision_sources else "unknown"),
        "paragraph_review_counts": paragraph_review_counts,
        "paragraph_pass_count": int(paragraph_review_counts.get("passed") or 0),
        "repair_target_count": repair_target_count,
        "unsupported_scope_summary": unsupported_scope_summary,
        "best_answer": draft if passed and draft else None,
        "best_answer_meta": best_answer_meta,
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "completed_at": now_iso(),
    }
    updates: dict[str, Any] = {
        "loop_counts": loop_counts_updates,
        "reflection": {
            **(
                state.get("reflection")
                if isinstance(state.get("reflection"), dict)
                else {}
            ),
            "review_passed": passed,
            "action": action,
            "reason": reason,
            "review_breakdown": by_check,
            "review_risk_level": review_risk_level,
            "review_confidence": stage_summary["review_confidence"],
            "review_decision_source": stage_summary["review_decision_source"],
        },
    }
    updates = {
        **updates,
        **_merge_stage_summary(state, "answer_review", stage_summary, updates=updates),
    }
    updates = {
        **updates,
        **_merge_stage_summary(
            state, "answer_review_fuse", stage_summary, updates=updates
        ),
    }
    updates = {
        **updates,
        **_merge_subgraph_state(
            state,
            {
                "phase": "answer_review_fuse",
                "last_updated_at": now_iso(),
            },
            updates=updates,
        ),
    }
    goto = "answer_commit" if passed else "answer_repair"
    generation_retries = int(loop_counts.get("generation_retries") or 0)
    max_generation_retries = int(settings.kb_chat_max_generation_retries)
    if (
        not passed
        and _is_repairable_review_failure(
            reason=_as_str(reason),
            citation=citation,
            answer=answer,
        )
        and generation_retries >= max_generation_retries
    ):
        goto = "answer_commit"
    elif not passed and not _is_repairable_review_failure(
        reason=_as_str(reason),
        citation=citation,
        answer=answer,
    ):
        goto = "answer_commit"
    _emit_review_event(
        {
            "event_type": "answer_review_fused",
            "passed": passed,
            "reason": reason,
            "goto": goto,
            "risk_level": review_risk_level,
            "fallback_reason": fallback_reason,
            "ts": now_iso(),
        }
    )
    return Command(update=updates, goto=goto)


async def _draft_generate(
    state: DraftGenerateInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    _ = runtime
    updates = await generate_draft(state, settings=settings, chat_model=chat_model)
    return {
        **updates,
        **_merge_subgraph_state(
            state,
            {
                "phase": "draft_generate",
                "last_updated_at": now_iso(),
            },
            updates=updates,
        ),
    }


async def _answer_repair(
    state: AnswerRepairInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    _ = runtime
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)
    loop_counts = {
        **loop_counts,
        "generation_retries": loop_counts["generation_retries"] + 1,
    }

    draft_answer = _as_str(state.get("draft_answer")).strip()
    raw_final_context = _as_str(state.get("final_context")).strip()
    evidence_labels, _, final_context = _resolve_allowed_citation_labels(
        state,
        final_context=raw_final_context,
    )
    question = _resolve_query_text(state)
    source_paragraphs = _load_answer_paragraphs(
        state,
        draft_answer=draft_answer,
    )
    source_render_meta = state.get("answer_render_meta")
    if not isinstance(source_render_meta, dict) and source_paragraphs:
        source_render_meta = _build_answer_render_meta_from_paragraphs(
            source_paragraphs
        )
    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}

    repaired_answer = draft_answer
    fallback_reason: str | None = None
    repair_mode = "llm_or_fallback"
    repaired_paragraphs: list[dict[str, Any]] | None = None
    repaired_render_meta: dict[str, Any] | None = None
    removed_auxiliary_claim_count = 0
    deterministic_repair = _maybe_repair_auxiliary_only_paragraphs(state)
    if deterministic_repair is not None:
        repaired_paragraphs, repaired_render_meta, repaired_answer = (
            deterministic_repair
        )
        fallback_reason = "deterministic_auxiliary_prune"
        repair_mode = "deterministic_auxiliary_prune"
        repaired_models = [
            AnswerParagraph.model_validate(paragraph)
            for paragraph in repaired_paragraphs
        ]
        removed_auxiliary_claim_count = max(
            _count_unsupported_auxiliary_claims(source_paragraphs)
            - _count_unsupported_auxiliary_claims(repaired_models),
            0,
        )
    elif (
        _as_str(reflection_obj.get("reason")).strip() == "unsupported_claims"
        and _resolve_unsupported_scope_from_state(state) != "auxiliary_only"
    ):
        fallback_reason = "repair_scope_not_supported"
        repair_mode = "scope_blocked"
    elif draft_answer and final_context and question and evidence_labels:
        prompts = get_prompt_loader()
        coverage_hint = _build_answer_coverage_hint(question, final_context)
        coverage_block = f"{coverage_hint}\n\n" if coverage_hint else ""
        try:
            repair_system = prompts.render_with_few_shot("kb_chat/system")
        except KeyError:
            repair_system = (
                "你是知识库回答修复器。"
                "仅基于参考内容修复回答并补齐有效引用，禁止新增无依据事实。"
            )
        repair_user = (
            "请修复回答，仅输出最终答案正文。\n"
            "要求：\n"
            "1) 仅使用参考内容中的事实；\n"
            "2) 采用段落级聚合引用：每段结尾统一附带有效 [Sx]；不要逐句强制补引；\n"
            "3) 若某段存在无法被支持的辅助断言，删除该辅助断言，不要强行补引；\n"
            "4) 若参考内容已出现某实体或术语，不得把该实体整体写成“资料不足”。\n"
            "5) 不能引入参考内容外信息。\n\n"
            f"{coverage_block}"
            f"问题：{question}\n\n"
            f"参考内容：\n{final_context}\n\n"
            f"原回答：\n{draft_answer}\n\n"
            "当前段落级元数据：\n"
            f"{_format_paragraph_review_payload(source_paragraphs)}"
        )
        model = chat_model.bind(max_tokens=1024)
        try:
            msg = await model.ainvoke(
                [
                    SystemMessage(content=repair_system),
                    HumanMessage(content=repair_user),
                ]
            )
            candidate = extract_answer_text(getattr(msg, "content", "")).strip()
            if candidate:
                (
                    repaired_paragraphs,
                    repaired_render_meta,
                    normalized_candidate,
                    projection_fallback_reason,
                ) = _project_repair_candidate(
                    candidate,
                    allowed_labels=evidence_labels,
                )
                if projection_fallback_reason:
                    fallback_reason = projection_fallback_reason
                    logger.warning(
                        "Answer repair 候选投影失败",
                        extra={
                            "projection_fallback_reason": projection_fallback_reason,
                            "candidate_preview": candidate[:1600],
                            "source_paragraph_count": len(source_paragraphs),
                            "source_citation_count": sum(
                                len(paragraph.citation_ids)
                                for paragraph in source_paragraphs
                            ),
                        },
                    )
                else:
                    repaired_answer = _as_str(normalized_candidate).strip()
                    repair_mode = "llm_rewrite"
                    repaired_models = [
                        AnswerParagraph.model_validate(paragraph)
                        for paragraph in repaired_paragraphs or []
                    ]
                    removed_auxiliary_claim_count = max(
                        _count_unsupported_auxiliary_claims(source_paragraphs)
                        - _count_unsupported_auxiliary_claims(repaired_models),
                        0,
                    )
            else:
                fallback_reason = "empty_repair_output"
        except asyncio.CancelledError:
            raise
        except Exception:
            fallback_reason = "repair_invoke_failed"
    else:
        fallback_reason = "repair_input_missing"

    subgraph_state = state.get("answer_subgraph_state")
    repair_attempts = (
        int(subgraph_state.get("repair_attempts") or 0)
        if isinstance(subgraph_state, dict)
        else 0
    ) + 1
    updates: dict[str, Any] = {
        "loop_counts": loop_counts,
        "draft_answer": repaired_answer,
        "final_answer": repaired_answer,
    }
    if repaired_paragraphs is not None and repaired_render_meta is not None:
        updates["answer_paragraphs"] = repaired_paragraphs
        updates["answer_render_meta"] = repaired_render_meta
    effective_render_meta = (
        repaired_render_meta
        if isinstance(repaired_render_meta, dict)
        else source_render_meta
    )
    rerendered_paragraph_count = (
        int(repaired_render_meta.get("paragraph_count") or 0)
        if isinstance(repaired_render_meta, dict)
        else 0
    )
    updates = {
        **updates,
        **_merge_stage_summary(
            state,
            "answer_repair",
            {
                "repair_attempt": repair_attempts,
                "repair_mode": repair_mode,
                "fallback_reason": fallback_reason,
                "removed_auxiliary_claim_count": removed_auxiliary_claim_count,
                "rerendered_paragraph_count": rerendered_paragraph_count,
                "paragraph_count": (
                    effective_render_meta.get("paragraph_count")
                    if isinstance(effective_render_meta, dict)
                    else None
                ),
                "claim_count": (
                    effective_render_meta.get("claim_count")
                    if isinstance(effective_render_meta, dict)
                    else None
                ),
                "citation_count": (
                    effective_render_meta.get("citation_count")
                    if isinstance(effective_render_meta, dict)
                    else None
                ),
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
            updates=updates,
        ),
        **_merge_subgraph_state(
            state,
            {
                "phase": "answer_repair",
                "repair_attempts": repair_attempts,
                "last_updated_at": now_iso(),
            },
            updates=updates,
        ),
    }
    return updates


async def _answer_commit(
    state: AnswerCommitInput,
    runtime: Runtime[KbChatAnswerSubgraphContext],
    *,
    settings: Settings,
) -> dict[str, Any]:
    _ = runtime
    reflection = state.get("reflection")
    reflection_obj = reflection if isinstance(reflection, dict) else {}
    loop_counts = _get_loop_counts(state)
    repair_attempts = 0
    subgraph_state = state.get("answer_subgraph_state")
    if isinstance(subgraph_state, dict):
        repair_attempts = int(subgraph_state.get("repair_attempts") or 0)

    next_step = _resolve_answer_subgraph_next_step(state, settings=settings)
    reason = _as_str(reflection_obj.get("reason")).strip().lower()
    review_passed = reflection_obj.get("review_passed") is True
    degrade_reason: str | None = None
    reflection_patch: dict[str, Any] = {}

    if not review_passed and loop_counts["generation_retries"] >= int(
        settings.kb_chat_max_generation_retries
    ):
        next_step = "force_exit"
        degrade_reason = "max_generation_retries"
        reflection_patch = {
            "action": "force_exit",
            "reason": "max_generation_retries",
            "review_passed": False,
        }
    elif next_step == "force_exit":
        degrade_reason = reason or "force_exit"
        reflection_patch = {"action": "force_exit", "reason": degrade_reason}
    elif next_step == "transform_query":
        degrade_reason = reason or "review_failed"
        reflection_patch = {"action": "transform_query", "reason": degrade_reason}
    else:
        reflection_patch = {"action": "none"}

    merged_reflection = {**reflection_obj, **reflection_patch}
    committed_answer = _as_str(
        state.get("final_answer") or state.get("draft_answer")
    ).strip()
    final_answer = committed_answer
    if not final_answer and next_step == "force_exit":
        final_answer = resolve_kb_refusal_answer(reason=degrade_reason or reason)
    best_answer = _as_str(state.get("best_answer")).strip()
    best_answer_meta = (
        state.get("best_answer_meta")
        if isinstance(state.get("best_answer_meta"), dict)
        else None
    )
    if next_step == "force_exit" and committed_answer and not best_answer:
        best_answer = committed_answer
        best_answer_meta = {
            "from_node": "answer_commit",
            "reason": degrade_reason or reason or "force_exit",
            "review_passed": review_passed,
            "repair_attempts": repair_attempts,
            "generation_retries": int(loop_counts.get("generation_retries") or 0),
            "completed_at": now_iso(),
        }

    summary = {
        "passed": merged_reflection.get("review_passed") is True,
        "reason": _as_str(merged_reflection.get("reason")).strip(),
        "next_step": next_step,
        "repair_attempts": repair_attempts,
        "generation_retries": loop_counts.get("generation_retries", 0),
        "retrieval_retries": loop_counts.get("retrieval_retries", 0),
        "best_answer": best_answer or None,
        "degrade_reason": degrade_reason,
        "completed_at": now_iso(),
    }

    updates: dict[str, Any] = {
        "reflection": merged_reflection,
        "degrade_reason": degrade_reason,
    }
    updates = {
        **updates,
        **merge_routing_decision(
            state,
            "answer_subgraph",
            {
                "phase": "answer_subgraph",
                "next_node": next_step,
                "action": _as_str(merged_reflection.get("action")).strip() or "none",
                "reason": _as_str(merged_reflection.get("reason")).strip(),
                "reason_code": _as_str(merged_reflection.get("reason_code")).strip(),
                "decision_source": "answer_commit",
                "retry_budget_snapshot": {
                    "generation_retries": int(
                        loop_counts.get("generation_retries") or 0
                    ),
                    "retrieval_retries": int(loop_counts.get("retrieval_retries") or 0),
                },
                "round_id": _current_review_round(state),
                "completed_at": now_iso(),
            },
            updates=updates,
        ),
    }
    if final_answer:
        updates["final_answer"] = final_answer
    if best_answer:
        updates["best_answer"] = best_answer
    if isinstance(best_answer_meta, dict):
        updates["best_answer_meta"] = best_answer_meta
    if next_step == "END":
        if not final_answer:
            final_answer = "根据现有资料无法回答该问题（未生成答案）。"
            updates["final_answer"] = final_answer
        updates["messages"] = [AIMessage(content=final_answer)]
    return {
        **updates,
        **_merge_stage_summary(state, "answer_subgraph", summary, updates=updates),
        **_merge_subgraph_state(
            state,
            {
                "phase": "answer_commit",
                "next_step": next_step,
                "repair_attempts": repair_attempts,
                "last_updated_at": now_iso(),
            },
            updates=updates,
        ),
    }


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

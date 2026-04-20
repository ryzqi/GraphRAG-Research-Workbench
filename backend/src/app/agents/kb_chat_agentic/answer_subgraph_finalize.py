"""KB Chat answer subgraph 生成、修复与提交节点。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.runtime import Runtime

from app.agents.kb_chat_agentic.reflection import (
    _build_answer_coverage_hint,
    generate_draft,
)
from app.agents.kb_chat_agentic.schemas import AnswerParagraph
from app.agents.kb_chat_agentic_state import (
    AnswerCommitInput,
    AnswerRepairInput,
    DraftGenerateInput,
    merge_routing_decision,
)
from app.core.settings import Settings
from app.prompts import get_prompt_loader
from app.services.evidence_guardrails import resolve_kb_refusal_answer
from app.services.streaming import extract_answer_text

from .answer_subgraph_review_helpers import (
    _count_unsupported_auxiliary_claims,
    _maybe_repair_auxiliary_only_paragraphs,
    _project_repair_candidate,
    _resolve_unsupported_scope_from_state,
)
from .answer_subgraph_shared import (
    KbChatAnswerSubgraphContext,
    _as_str,
    _build_answer_render_meta_from_paragraphs,
    _current_review_round,
    _format_paragraph_review_payload,
    _get_loop_counts,
    _load_answer_paragraphs,
    _merge_stage_summary,
    _merge_subgraph_state,
    _resolve_allowed_citation_labels,
    _resolve_answer_subgraph_next_step,
    _resolve_query_text,
)
from .budget import now_iso
from .output_token_budget import resolve_kb_chat_repair_max_tokens

logger = logging.getLogger('app.agents.kb_chat_agentic.answer_subgraph')

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
        model = chat_model.bind(max_tokens=resolve_kb_chat_repair_max_tokens(settings))
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



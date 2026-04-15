"""KB Chat agentic reflection 草稿生成节点。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import time
from typing import Any

from langchain.messages import HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.settings import Settings
from app.prompts import get_prompt_loader
from app.services.kb_answer_paragraphs import render_answer_paragraphs
from app.services.streaming import extract_answer_text

from .budget import now_iso
from .reflection_draft_utils import (
    _attempt_local_plain_text_draft_repair,
    _build_answer_coverage_hint,
    _build_answer_render_meta,
    _build_draft_retry_chat_model,
    _can_project_plain_text_after_structured_failure,
    _detect_draft_coverage_gap,
    _extract_allowed_citation_ids,
    _invoke_draft_structured,
    _project_plain_text_answer_to_paragraphs,
    _should_retry_draft_structured,
)
from .reflection_shared import (
    _as_str,
    _get_loop_counts,
    _merge_stage_summary,
    _resolve_query_text,
    _set_final_answer_for_exit,
    _total_rounds_exceeded,
)


async def generate_draft(
    state: Mapping[str, object],
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    """仅基于 Top-N final_context 生成草稿答案；不要追加到 messages。"""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)

    # 预算统计：每次生成都记作一轮。
    loop_counts = {**loop_counts, "total_rounds": loop_counts["total_rounds"] + 1}

    if _total_rounds_exceeded(loop_counts, settings):
        # 若存在当前最优草稿，则优先使用。
        return {
            "loop_counts": loop_counts,
            **_set_final_answer_for_exit(
                state, _as_str(state.get("draft_answer")), reason="max_total_rounds"
            ),
        }
    if loop_counts["generation_retries"] > int(settings.kb_chat_max_generation_retries):
        return {
            "loop_counts": loop_counts,
            **_set_final_answer_for_exit(
                state,
                _as_str(state.get("draft_answer")),
                reason="max_generation_retries",
            ),
        }

    question = _resolve_query_text(state)
    final_context = _as_str(state.get("final_context")).strip()
    coverage_hint = _build_answer_coverage_hint(question, final_context)
    coverage_block = f"{coverage_hint}\n\n" if coverage_hint else ""
    prompts = get_prompt_loader()
    system_prompt = prompts.render_with_few_shot("kb_chat/system")

    user = (
        "请基于参考内容回答问题，并按结构化段落返回。\n"
        "要求：\n"
        "1) paragraphs 按自然段组织，每段 text 只写正文，不要内嵌 [Sx] 标签；\n"
        "2) citation_ids 只填写该段主旨所依赖的可见引用标签，如 S1、S2；\n"
        "3) 默认采用段末聚合引用，不要求逐句引用，但段内关键结论必须能被该段 citation_ids 支撑；\n"
        "4) claims 仅保留该段关键断言；supporting_citation_ids 只填有效 Sx 标签；\n"
        "5) 若参考内容不足以形成可回答段落，返回空 paragraphs，不要编造。\n"
        "6) 不要输出 Markdown 代码块、解释性前言或 schema 外字段。\n\n"
        f"{coverage_block}"
        f"参考内容：\n{final_context}\n\n"
        f"问题：{question}"
    )

    structured_reason: str | None = None
    paragraph_payloads: list[dict[str, Any]] = []
    render_meta = _build_answer_render_meta([])
    draft = ""
    draft_messages: list[SystemMessage | HumanMessage] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user),
    ]

    (
        paragraph_payloads,
        render_meta,
        draft,
        structured_reason,
    ) = await _invoke_draft_structured(
        chat_model=chat_model,
        messages=draft_messages,
    )

    if not draft and _should_retry_draft_structured(structured_reason):
        retry_chat_model = _build_draft_retry_chat_model(settings=settings)
        if retry_chat_model is not None:
            (
                retry_paragraph_payloads,
                retry_render_meta,
                retry_draft,
                retry_reason,
            ) = await _invoke_draft_structured(
                chat_model=retry_chat_model,
                messages=draft_messages,
            )
            if retry_draft:
                paragraph_payloads = retry_paragraph_payloads
                render_meta = retry_render_meta
                draft = retry_draft
                structured_reason = retry_reason
            else:
                structured_reason = retry_reason or structured_reason

    if not draft:
        if (
            _can_project_plain_text_after_structured_failure(structured_reason)
            and final_context
            and question
        ):
            plain_user = (
                "请基于参考内容直接回答问题，仅输出最终答案正文。\n"
                "要求：\n"
                "1) 仅使用参考内容中的事实；\n"
                "2) 默认采用段落级聚合引用：每段结尾统一附带有效 [Sx]；\n"
                "3) 若问题同时要求多个必答子项，必须逐一覆盖；\n"
                "4) 若参考内容已出现某实体或术语，不得把该实体整体写成“资料不足”。\n"
                "5) 不要输出 JSON、代码块或额外解释。\n\n"
                f"{coverage_block}"
                f"参考内容：\n{final_context}\n\n"
                f"问题：{question}"
            )
            try:
                plain_model = chat_model.bind(max_tokens=1024)
                plain_msg = await plain_model.ainvoke(
                    [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=plain_user),
                    ]
                )
                candidate = extract_answer_text(
                    getattr(plain_msg, "content", "")
                ).strip()
                projected = _project_plain_text_answer_to_paragraphs(
                    candidate,
                    allowed_citation_ids=_extract_allowed_citation_ids(final_context),
                )
                if projected:
                    paragraph_payloads = [
                        paragraph.model_dump() for paragraph in projected
                    ]
                    render_meta = _build_answer_render_meta(projected)
                    draft = render_answer_paragraphs(paragraph_payloads).strip()
                    structured_reason = (
                        f"{structured_reason}_recovered_by_plain_text_projection"
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        if not draft:
            if structured_reason == "empty_structured_paragraphs":
                draft = "根据现有资料无法回答该问题。"
            else:
                draft = "根据现有资料无法回答该问题（生成失败）。"
    elif final_context and question:
        coverage_gap = _detect_draft_coverage_gap(
            question=question,
            draft=draft,
            final_context=final_context,
        )
        if coverage_gap is not None:
            repaired = await _attempt_local_plain_text_draft_repair(
                chat_model=chat_model,
                system_prompt=system_prompt,
                question=question,
                final_context=final_context,
                coverage_block=coverage_block,
                draft=draft,
                coverage_gap=coverage_gap,
            )
            if repaired is not None:
                paragraph_payloads, render_meta, draft = repaired

    generator_summary = {
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "paragraph_count": int(render_meta.get("paragraph_count") or 0),
        "claim_count": int(render_meta.get("claim_count") or 0),
        "citation_count": int(render_meta.get("citation_count") or 0),
        "citation_mode": render_meta.get("citation_mode") or "paragraph_aggregate",
        "fallback_reason": structured_reason,
        "completed_at": now_iso(),
    }
    summary_updates = _merge_stage_summary(state, "generator", generator_summary)
    draft_generate_state = {
        **state,
        **summary_updates,
    }
    summary_updates.update(
        _merge_stage_summary(
            draft_generate_state,
            "draft_generate",
            {
                "paragraph_count": int(render_meta.get("paragraph_count") or 0),
                "claim_count": int(render_meta.get("claim_count") or 0),
                "citation_count": int(render_meta.get("citation_count") or 0),
                "citation_mode": render_meta.get("citation_mode")
                or "paragraph_aggregate",
                "completed_at": now_iso(),
            },
        )
    )

    return {
        "loop_counts": loop_counts,
        "answer_paragraphs": paragraph_payloads,
        "answer_render_meta": render_meta,
        "draft_answer": draft,
        # 保持 final_answer 同步，确保 ForceExit 始终能返回合理内容。
        "final_answer": draft,
        **summary_updates,
    }



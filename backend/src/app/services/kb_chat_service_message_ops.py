from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import select

from app.integrations.llm_client import ChatMessage as LLMMessage
from app.models.agent_run import AgentRunStatus
from app.models.chat_message import ChatMessage
from app.schemas.chats import (
    PendingClarification,
)
from app.services.evidence_guardrails import (
    is_kb_refusal_answer,
    resolve_kb_refusal_answer,
)
from app.services.streaming import (
    extract_answer_text,
)
from app.agents.kb_chat_agentic_state import (
    resolve_terminal_routing_decision,
)

logger = logging.getLogger(__name__)

async def _load_history(
    self, session_id: uuid.UUID, limit: int
) -> list[LLMMessage]:
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit * 2)
    )
    result = await self._db.execute(stmt)
    messages = list(result.scalars().all())
    messages.reverse()
    filtered = [
        m for m in messages if not self._summary_service.is_summary_message(m)
    ]
    if len(filtered) > limit:
        filtered = filtered[-limit:]
    return [
        LLMMessage(role=msg.role.value, content=msg.content) for msg in filtered
    ]

def _to_langchain_message(self, 
    msg: LLMMessage,
) -> SystemMessage | HumanMessage | AIMessage:
    role = (msg.role or "").lower()
    if role == "system":
        return SystemMessage(content=msg.content)
    if role == "assistant":
        return AIMessage(content=msg.content)
    return HumanMessage(content=msg.content)

def _default_clarification_message(self, ) -> str:
    return "为了更准确地回答，请补充对象、范围、时间或指标等关键信息。"

def _coerce_pending_clarification(self, payload: Any) -> PendingClarification | None:
    if not isinstance(payload, dict):
        return None
    try:
        return PendingClarification.model_validate(payload)
    except Exception:
        return None

def _resolve_terminal_reason(self, 
    *,
    clarification_payload: dict[str, Any] | None = None,
    routing_decisions: dict[str, Any] | None = None,
    reflection: dict[str, Any] | None = None,
    degrade_reason: str | None = None,
) -> str | None:
    if isinstance(clarification_payload, dict):
        return "clarify"
    _, terminal_route = resolve_terminal_routing_decision(
        {"routing_decisions": routing_decisions or {}},
        next_nodes={"force_exit"},
    )
    if terminal_route:
        action = str(terminal_route.get("action") or "").strip().lower()
        if action == "clarify":
            return "clarify"
        reason = str(terminal_route.get("reason") or "").strip().lower()
        if reason and reason not in {"passed", "none"}:
            return reason
        if (
            str(terminal_route.get("next_node") or "").strip().lower()
            == "force_exit"
        ):
            return "force_exit"
    if isinstance(degrade_reason, str) and degrade_reason.strip():
        return degrade_reason.strip().lower()
    if isinstance(reflection, dict):
        action = str(reflection.get("action") or "").strip().lower()
        if action == "clarify":
            return "clarify"
        if action not in {"force_exit", "transform_query"}:
            return None
        reason = str(reflection.get("reason") or "").strip().lower()
        if reason and reason not in {"passed", "none"}:
            return reason
        if action == "force_exit":
            return "force_exit"
    return None

def _extract_clarification_pending(
    cls,
    *,
    clarification_payload: dict[str, Any] | None,
    answer: str,
    reflection: dict[str, Any] | None = None,
) -> tuple[str | None, PendingClarification | None]:
    reason = cls._resolve_terminal_reason(
        clarification_payload=clarification_payload,
        reflection=reflection,
    )
    if reason != "clarify":
        return None, None

    pending_clarification = cls._coerce_pending_clarification(clarification_payload)

    text = extract_answer_text(answer).strip()
    if not text and pending_clarification is not None:
        text = pending_clarification.question
    if not text:
        text = cls._default_clarification_message()

    if pending_clarification is None:
        pending_clarification = PendingClarification(
            question=text,
            reason_code="mixed",
            confidence=0.0,
            model_reason=None,
            slots=[],
            suggested_answers=[],
        )

    return text, pending_clarification

def _resolve_terminal_run_status(self, 
    *,
    answer: str,
    clarification_payload: dict[str, Any] | None = None,
    routing_decisions: dict[str, Any] | None = None,
    reflection: dict[str, Any] | None = None,
    best_answer: str | None = None,
) -> tuple[AgentRunStatus, str | None]:
    """根据规范状态与最终答案解析终态运行状态。"""
    reason = self._resolve_terminal_reason(
        clarification_payload=clarification_payload,
        routing_decisions=routing_decisions,
        reflection=reflection,
    )
    if reason == "clarify":
        return AgentRunStatus.SUCCEEDED, None

    _, terminal_route = resolve_terminal_routing_decision(
        {"routing_decisions": routing_decisions or {}},
        next_nodes={"force_exit"},
    )
    terminal_force_exit = bool(terminal_route)
    review_passed = (
        reflection.get("review_passed")
        if isinstance(reflection, dict) and not terminal_force_exit
        else False
        if terminal_force_exit
        else None
    )
    answer_text = extract_answer_text(answer).strip()
    canonical_best_answer = (
        extract_answer_text(best_answer).strip() if best_answer else ""
    )
    best_answer_matches = (
        not terminal_force_exit
        and bool(canonical_best_answer)
        and answer_text == canonical_best_answer
    )
    if (
        (review_passed is True or best_answer_matches)
        and answer_text
        and "无法回答" not in answer_text
    ):
        return AgentRunStatus.SUCCEEDED, None

    if not reason:
        return AgentRunStatus.SUCCEEDED, None

    if answer_text and is_kb_refusal_answer(answer_text):
        return AgentRunStatus.FAILED, answer_text

    message = resolve_kb_refusal_answer(reason=reason)
    return AgentRunStatus.FAILED, message

def _build_no_evidence_response(self, 
    *,
    reason_code: str | None,
    stage_summaries: dict[str, Any],
    selected_kb_ids: list[uuid.UUID] | None,
) -> str:
    normalized_reason_code = str(reason_code or "").strip().lower()

    reason_text_map = {
        "clarify": "当前问题信息不足，需要先补充关键条件",
        "max_total_rounds": "多轮检索与校验后仍无可用证据",
        "max_retrieval_retries": "多次重写检索后仍未命中相关证据",
        "max_generation_retries": "多次生成与校验后仍无法得到可引用答案",
        "fallback_closed": "评估器触发保守策略，未通过证据校验",
        "severe_conflict": "检索证据出现明显冲突，无法稳定作答",
        "conflict_retry_exhausted": "冲突证据重试后仍未收敛",
    }
    reason_text = reason_text_map.get(
        normalized_reason_code, "未检索到可用于回答的证据片段"
    )

    stage_label_map = {
        "merge_context": "上下文合并",
        "resolve_reference": "指代消解",
        "ambiguity_check": "歧义检测",
        "query_normalize": "问题规范化",
        "query_plan": "查询规划",
        "decomposition": "问题拆解",
        "generate_variants": "多路查询扩展",
        "hyde": "假设文档扩展",
        "query_plan_finalize": "查询定稿",
        "retrieval": "检索融合",
        "answer_subgraph": "答案子图",
        "generator": "答案生成",
        "answer_review": "答案审查",
        "answer_repair": "答案修复",
        "transform_query": "重写检索问题",
        "force_exit": "提前终止",
        "service_guardrail": "服务保护",
    }
    executed = [
        label
        for key, label in stage_label_map.items()
        if key in stage_summaries and isinstance(stage_summaries.get(key), dict)
    ]
    executed_text = (
        " -> ".join(executed[:8])
        if executed
        else "问题理解 -> 检索证据 -> 回答校验"
    )

    kb_count = len(selected_kb_ids or [])
    suggestions = [
        "把问题改得更具体（增加实体名、时间范围、指标口径）后重试。",
        "只保留最相关的 1-2 个知识库，避免检索范围过宽。",
        "若资料尚未入库，请先补充文档再提问。",
    ]
    if normalized_reason_code == "clarify":
        suggestions[0] = "先补充缺失条件（对象、时间、范围）后继续提问。"

    return (
        "我暂时无法从当前知识库中找到足够证据来回答这个问题。\n\n"
        f"原因：{reason_text}\n"
        f"已执行流程：{executed_text}\n"
        f"当前知识库范围：{kb_count} 个。\n\n"
        "建议下一步：\n"
        f"1) {suggestions[0]}\n"
        f"2) {suggestions[1]}\n"
        f"3) {suggestions[2]}"
    )

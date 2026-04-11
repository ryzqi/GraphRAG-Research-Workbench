from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from langgraph.types import Interrupt

from app.agents.general_chat_agent import build_pending_tool_calls
from app.core.checkpoint import CheckpointManager
from app.core.errors import AppError
from app.models.agent_run import AgentRun
from app.models.chat_session import ChatSession
from app.schemas.chats import (
    AgentRunRead,
    ChatPendingToolApprovalResponse,
    PendingInterruptApproval,
    PendingToolCall,
    ToolApprovalRequest,
)
from app.services.streaming import StreamState

logger = logging.getLogger(__name__)


def _extract_interrupt_message(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message
    action_requests = payload.get("action_requests")
    if isinstance(action_requests, list):
        for item in action_requests:
            if not isinstance(item, dict):
                continue
            desc = item.get("description")
            if isinstance(desc, str) and desc.strip():
                return desc
    return None


def _extract_interrupt_payload(interrupt: object) -> dict[str, Any] | None:
    if isinstance(interrupt, Interrupt):
        return interrupt.value if isinstance(interrupt.value, dict) else None
    if isinstance(interrupt, dict):
        value = interrupt.get("value")
        if isinstance(value, dict):
            return value
        if "action_requests" in interrupt:
            return interrupt
        return None
    value = getattr(interrupt, "value", None)
    return value if isinstance(value, dict) else None


def _extract_interrupt_id(interrupt: object) -> str | None:
    if isinstance(interrupt, Interrupt):
        if isinstance(interrupt.id, str) and interrupt.id.strip():
            return interrupt.id
        if isinstance(interrupt.value, dict):
            nested_id = interrupt.value.get("id")
            if isinstance(nested_id, str) and nested_id.strip():
                return nested_id
        return None
    if isinstance(interrupt, dict):
        interrupt_id = interrupt.get("id")
        if isinstance(interrupt_id, str) and interrupt_id.strip():
            return interrupt_id
        value = interrupt.get("value")
        if isinstance(value, dict):
            nested_id = value.get("id")
            if isinstance(nested_id, str) and nested_id.strip():
                return nested_id
        return None
    interrupt_id = getattr(interrupt, "id", None)
    if isinstance(interrupt_id, str) and interrupt_id.strip():
        return interrupt_id
    payload = getattr(interrupt, "value", None)
    if isinstance(payload, dict):
        nested_id = payload.get("id")
        if isinstance(nested_id, str) and nested_id.strip():
            return nested_id
    return None


def _flatten_interrupts(interrupts: list[object]) -> list[object]:
    flat: list[object] = []
    for interrupt in interrupts:
        if isinstance(interrupt, list):
            flat.extend(interrupt)
            continue
        flat.append(interrupt)
    return flat


def _build_interrupt_entries(interrupts: list[object]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index, interrupt in enumerate(_flatten_interrupts(interrupts)):
        payload = _extract_interrupt_payload(interrupt)
        if not isinstance(payload, dict):
            continue
        raw_requests = payload.get("action_requests")
        action_requests: list[dict[str, Any]] = []
        if isinstance(raw_requests, list):
            action_requests = [item for item in raw_requests if isinstance(item, dict)]
        interrupt_id = _extract_interrupt_id(interrupt) or f"interrupt_{index + 1}"
        entries.append(
            {
                "interrupt_id": interrupt_id,
                "message": _extract_interrupt_message(payload),
                "action_requests": action_requests,
            }
        )
    return entries


def _extract_action_requests(interrupts: list[object]) -> list[dict[str, Any]]:
    action_requests: list[dict[str, Any]] = []
    for entry in _build_interrupt_entries(interrupts):
        action_requests.extend(entry["action_requests"])
    return action_requests


def _extract_pending_interrupts(pending_writes: object) -> list[object]:
    if not isinstance(pending_writes, list):
        return []
    interrupts: list[object] = []
    for item in pending_writes:
        channel = None
        value = None
        if isinstance(item, tuple):
            if len(item) > 1:
                channel = item[1]
            if len(item) > 2:
                value = item[2]
        else:
            channel = getattr(item, "channel", None)
            value = getattr(item, "value", None)
        if channel != "__interrupt__" or value is None:
            continue
        if isinstance(value, list):
            interrupts.extend(value)
            continue
        interrupts.append(value)
    return interrupts


async def get_pending_tool_approval(
    self,
    *,
    session: ChatSession,
    run: AgentRun | None = None,
) -> ChatPendingToolApprovalResponse | None:
    current_run = run or await self._get_running_general_run(session_id=session.id)
    if current_run is None:
        return None

    checkpoint_tuple = await CheckpointManager.get_state(str(session.id))
    if checkpoint_tuple is None:
        return None
    pending_interrupts_raw = _extract_pending_interrupts(
        checkpoint_tuple.pending_writes
    )
    if not pending_interrupts_raw:
        return None

    try:
        _, tool_meta_by_name = await self._load_tool_registry_for_session(
            session=session
        )
    except Exception:
        logger.warning(
            "Failed to load tool registry while recovering pending approvals; fallback to name parsing",
            extra={"session_id": str(session.id), "run_id": str(current_run.id)},
        )
        tool_meta_by_name = {}
    pending_interrupts = self._build_pending_interrupt_approvals(
        pending_interrupts_raw,
        tool_meta_by_name,
    )
    return ChatPendingToolApprovalResponse(
        thread_id=str(session.id),
        pending_interrupts=[
            PendingInterruptApproval(
                interrupt_id=item["interrupt_id"],
                message=item.get("message"),
                pending_tool_calls=[
                    PendingToolCall.model_validate(call)
                    for call in item.get("pending_tool_calls", [])
                    if isinstance(call, dict)
                ],
            )
            for item in pending_interrupts
            if isinstance(item, dict)
        ],
        run=AgentRunRead.model_validate(current_run),
    )


@staticmethod
def _build_pending_interrupt_approvals(
    interrupts: list[object],
    tool_meta_by_name: dict[str, Any],
) -> list[dict[str, Any]]:
    approvals: list[dict[str, Any]] = []
    for entry in _build_interrupt_entries(interrupts):
        pending_tool_calls = build_pending_tool_calls(
            entry["action_requests"],
            tool_meta_by_name,
        )
        approvals.append(
            {
                "interrupt_id": entry["interrupt_id"],
                "message": entry["message"],
                "pending_tool_calls": pending_tool_calls,
                "action_requests": entry["action_requests"],
            }
        )
    return approvals


@staticmethod
def _build_interrupt_stage_summary(
    pending_interrupts: list[dict[str, Any]],
) -> dict[str, Any]:
    interrupt_ids = [
        str(item["interrupt_id"])
        for item in pending_interrupts
        if isinstance(item.get("interrupt_id"), str)
    ]
    tool_count = sum(
        len(item.get("pending_tool_calls", []))
        for item in pending_interrupts
        if isinstance(item.get("pending_tool_calls"), list)
    )
    return {
        "pending": True,
        "tool_count": tool_count,
        "interrupt_count": len(interrupt_ids),
        "interrupt_ids": interrupt_ids,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }


@staticmethod
def _to_pending_interrupt_models(
    pending_interrupts: list[dict[str, Any]],
) -> list[PendingInterruptApproval]:
    return [
        PendingInterruptApproval(
            interrupt_id=item["interrupt_id"],
            message=item.get("message"),
            pending_tool_calls=[
                PendingToolCall.model_validate(call)
                for call in item.get("pending_tool_calls", [])
                if isinstance(call, dict)
            ],
        )
        for item in pending_interrupts
        if isinstance(item, dict)
    ]


async def _recover_stream_pending_tool_approval(
    self,
    *,
    thread_id: str,
    run: AgentRun,
    stream_state: StreamState,
    tool_meta_by_name: dict[str, Any],
    started_at: datetime,
    replay_metrics: dict[str, object],
    preserve_existing_metrics: bool = False,
) -> ChatPendingToolApprovalResponse | None:
    checkpoint_tuple = await CheckpointManager.get_state(thread_id)
    if checkpoint_tuple is None:
        return None
    pending_interrupts_raw = _extract_pending_interrupts(
        checkpoint_tuple.pending_writes
    )
    if not pending_interrupts_raw:
        return None

    pending_interrupts = self._build_pending_interrupt_approvals(
        pending_interrupts_raw,
        tool_meta_by_name,
    )
    if not pending_interrupts:
        return None

    context_metrics = self._build_context_metrics(stream_state.messages)
    run.stage_summaries = {
        "tool_approval": self._build_interrupt_stage_summary(pending_interrupts)
    }

    next_metrics = {
        "latency_ms": int(
            (datetime.now(timezone.utc) - started_at).total_seconds() * 1000
        ),
        "context": context_metrics,
        **replay_metrics,
        **(stream_state.metrics if isinstance(stream_state.metrics, dict) else {}),
    }
    if preserve_existing_metrics and isinstance(run.metrics, dict):
        next_metrics = {**run.metrics, **next_metrics}
    run.metrics = next_metrics

    await self._db.commit()
    await self._db.refresh(run)
    return ChatPendingToolApprovalResponse(
        thread_id=thread_id,
        pending_interrupts=self._to_pending_interrupt_models(pending_interrupts),
        run=AgentRunRead.model_validate(run),
    )


@staticmethod
def _build_resume_decisions_payload(
    pending_interrupts: list[dict[str, Any]],
    approval: ToolApprovalRequest,
) -> dict[str, Any]:
    pending_ids = [
        item["interrupt_id"]
        for item in pending_interrupts
        if isinstance(item.get("interrupt_id"), str)
    ]
    requested_map = {item.interrupt_id: item for item in approval.interrupts}
    if len(requested_map) != len(approval.interrupts):
        raise AppError(
            code="TOOL_APPROVAL_PAYLOAD_INVALID",
            message="审批请求包含重复的 interrupt_id",
            status_code=400,
        )

    missing = [
        interrupt_id
        for interrupt_id in pending_ids
        if interrupt_id not in requested_map
    ]
    pending_id_set = set(pending_ids)
    extra = [
        interrupt_id
        for interrupt_id in requested_map
        if interrupt_id not in pending_id_set
    ]
    if missing or extra:
        raise AppError(
            code="TOOL_APPROVAL_PAYLOAD_INVALID",
            message="审批请求与当前待审批中断不匹配",
            status_code=400,
            details={
                "missing_interrupt_ids": missing,
                "extra_interrupt_ids": extra,
            },
        )

    decision_map: dict[str, dict[str, Any]] = {}
    for item in pending_interrupts:
        interrupt_id = item.get("interrupt_id")
        if not isinstance(interrupt_id, str):
            continue
        action_requests = item.get("action_requests")
        if not isinstance(action_requests, list):
            action_requests = []
        batch = requested_map.get(interrupt_id)
        if batch is None:
            raise AppError(
                code="TOOL_APPROVAL_PAYLOAD_INVALID",
                message="审批请求缺少待审批中断",
                status_code=400,
            )
        if len(batch.decisions) != len(action_requests):
            raise AppError(
                code="TOOL_APPROVAL_PAYLOAD_INVALID",
                message="审批决策数量与工具调用数量不一致",
                status_code=400,
                details={
                    "interrupt_id": interrupt_id,
                    "expected": len(action_requests),
                    "actual": len(batch.decisions),
                },
            )
        decision_map[interrupt_id] = {
            "decisions": [
                decision.model_dump(mode="json", exclude_none=True)
                for decision in batch.decisions
            ]
        }

    if len(decision_map) == 1:
        only = next(iter(decision_map.values()))
        return {"decisions": only["decisions"]}
    return decision_map

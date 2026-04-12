"""普通代理服务。

使用 LangChain create_agent + LangGraph checkpointer，实现中间件与 Human-in-the-loop。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import partial
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.integrations.llm_client import LLMClient
from app.integrations.redis_client import RedisClient
from app.models.agent_run import AgentRun
from app.models.chat_session import ChatSession
from app.prompts import get_prompt_loader
from app.schemas.chats import (
    ChatAnswerResponse,
    ChatPendingToolApprovalResponse,
    ToolApprovalRequest,
)
from app.services import general_chat_service_dedup as general_dedup
from app.services import general_chat_service_execution as general_execution
from app.services import general_chat_service_interrupts as general_interrupts
from app.services import general_chat_service_runtime as general_runtime
from app.services.context_builder import ContextBuilder

_STATIC_HELPERS: dict[str, Any] = {
    '_normalize_client_request_id': general_dedup._normalize_client_request_id,
    '_is_missing_dedup_table_error': general_dedup._is_missing_dedup_table_error,
    '_serialize_external_evidence_locator': general_dedup._serialize_external_evidence_locator,
    '_evidence_item_from_row': general_dedup._evidence_item_from_row,
    '_is_summary_message': general_runtime._is_summary_message,
    '_map_llm_exception': general_runtime._map_llm_exception,
    '_build_agent_messages': general_runtime._build_agent_messages,
    '_message_text_for_metrics': general_runtime._message_text_for_metrics,
    '_supports_openai_response_replay': general_runtime._supports_openai_response_replay,
    '_drop_trailing_user_message': general_runtime._drop_trailing_user_message,
    '_build_pending_interrupt_approvals': general_interrupts._build_pending_interrupt_approvals,
    '_build_interrupt_stage_summary': general_interrupts._build_interrupt_stage_summary,
    '_to_pending_interrupt_models': general_interrupts._to_pending_interrupt_models,
    '_build_resume_decisions_payload': general_interrupts._build_resume_decisions_payload,
    '_extract_upstream_error_message': general_execution._extract_upstream_error_message,
    '_is_previous_response_not_found_error': general_execution._is_previous_response_not_found_error,
    '_should_recover_from_response_not_found': general_execution._should_recover_from_response_not_found,
    '_manual_replay_decision': general_execution._manual_replay_decision,
    '_build_replay_metrics': general_execution._build_replay_metrics,
}

_INSTANCE_HELPERS: dict[str, Any] = {
    '_handle_missing_dedup_table_error': general_dedup._handle_missing_dedup_table_error,
    '_claim_request_dedup': general_dedup._claim_request_dedup,
    '_wait_for_dedup_binding': general_dedup._wait_for_dedup_binding,
    '_delete_unbound_request_dedup': general_dedup._delete_unbound_request_dedup,
    '_persist_failed_run': general_dedup._persist_failed_run,
    '_wait_for_run_terminal': general_dedup._wait_for_run_terminal,
    '_get_latest_assistant_message': general_dedup._get_latest_assistant_message,
    '_get_assistant_message_for_user_message': general_dedup._get_assistant_message_for_user_message,
    '_build_success_response_from_run': general_dedup._build_success_response_from_run,
    '_list_run_evidence': general_dedup._list_run_evidence,
    '_persist_external_evidence': general_dedup._persist_external_evidence,
    '_replay_dedup_request': general_dedup._replay_dedup_request,
    '_load_tool_registry_for_session': general_runtime._load_tool_registry_for_session,
    '_load_runtime_tool_registry_for_session': general_runtime._load_runtime_tool_registry_for_session,
    '_open_runtime_tool_registry_for_session': general_runtime._open_runtime_tool_registry_for_session,
    '_close_runtime_tool_registry': general_runtime._close_runtime_tool_registry,
    '_load_history': general_runtime._load_history,
    '_build_summary_trigger': general_runtime._build_summary_trigger,
    '_resolve_replay_decision': general_runtime._resolve_replay_decision,
    '_requires_assistant_response_id_for_replay': general_runtime._requires_assistant_response_id_for_replay,
    '_sanitize_history_for_replay': general_runtime._sanitize_history_for_replay,
    '_build_context_metrics': general_runtime._build_context_metrics,
    '_recover_stream_pending_tool_approval': general_interrupts._recover_stream_pending_tool_approval,
    '_get_running_general_run': general_execution._get_running_general_run,
    '_ensure_no_running_general_run': general_execution._ensure_no_running_general_run,
    '_ensure_resume_target_valid': general_execution._ensure_resume_target_valid,
    '_finalize_run': general_execution._finalize_run,
}


class GeneralChatService:
    """普通代理服务，支持 MCP 扩展调用和检查点持久化。"""

    def __init__(
        self,
        db: AsyncSession,
        llm: LLMClient,
        *,
        redis: RedisClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._db = db
        self._llm = llm
        self._settings = get_settings()
        self._context_builder = ContextBuilder(self._settings)
        self._prompts = get_prompt_loader()
        self._redis = redis
        self._http_client = http_client
        self._dedup_missing_table_warned = False
        self._active_tool_runtime_cm: Any | None = None

    def __getattr__(self, name: str) -> Any:
        helper = _STATIC_HELPERS.get(name)
        if helper is not None:
            return helper
        helper = _INSTANCE_HELPERS.get(name)
        if helper is not None:
            return partial(helper, self)
        raise AttributeError(f'{type(self).__name__!s} has no attribute {name!r}')

    async def get_pending_tool_approval(
        self,
        *,
        session: ChatSession,
        run: AgentRun | None = None,
    ) -> ChatPendingToolApprovalResponse | None:
        return await general_interrupts.get_pending_tool_approval(
            self,
            session=session,
            run=run,
        )

    async def answer(
        self,
        *,
        session: ChatSession,
        user_content: str,
        client_request_id: str | None = None,
    ) -> ChatAnswerResponse | ChatPendingToolApprovalResponse:
        return await general_execution.answer(
            self,
            session=session,
            user_content=user_content,
            client_request_id=client_request_id,
        )

    def answer_stream(
        self,
        *,
        session: ChatSession,
        user_content: str,
        request: object | None = None,
        client_request_id: str | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        return general_execution.answer_stream(
            self,
            session=session,
            user_content=user_content,
            request=request,
            client_request_id=client_request_id,
        )

    async def resume_after_tool_approval(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
        approval: ToolApprovalRequest,
    ) -> ChatAnswerResponse | ChatPendingToolApprovalResponse:
        return await general_execution.resume_after_tool_approval(
            self,
            session=session,
            run=run,
            approval=approval,
        )

    def resume_after_tool_approval_stream(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
        approval: ToolApprovalRequest,
        request: object | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        return general_execution.resume_after_tool_approval_stream(
            self,
            session=session,
            run=run,
            approval=approval,
            request=request,
        )

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from sqlalchemy import select

from app.agents.kb_chat_memory import (
    resolve_kb_chat_store_user_id,
)
from app.agents.tool_calling.registry import build_tool_registry
from app.agents.tools.kb_retrieve import build_kb_retrieve_tool
from app.core.checkpoint import CheckpointManager
from app.core.errors import AppError
from app.core.logging import set_run_id
from app.core.memory_store import StoreManager
from app.integrations.chat_model_factory import (
    create_chat_model,
)
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.schemas.chats import (
    KbChatConfig,
)
from app.agents.kb_chat_contracts import (
    STATE_SCHEMA_V3,
)

from app.services.kb_chat_service_contracts import (
    _CheckpointRestorePlan,
    _KB_CHAT_CHECKPOINT_RESET_FIELDS,
    _KbChatExecution,
    _KbRetrievalBuffer,
)

logger = logging.getLogger(__name__)
async def _apply_gray_release_rollback_policy(
    self,
    *,
    kb_chat_config: KbChatConfig,
) -> tuple[KbChatConfig, dict[str, Any] | None]:
    return kb_chat_config, None

def _sanitize_checkpoint_messages(self, 
    messages: Any,
) -> list[SystemMessage | HumanMessage | AIMessage]:
    if not isinstance(messages, list):
        return []

    sanitized: list[SystemMessage | HumanMessage | AIMessage] = []
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            continue
        if isinstance(message, (SystemMessage, HumanMessage)):
            sanitized.append(message)
            continue
        if not isinstance(message, AIMessage):
            continue
        tool_calls = getattr(message, "tool_calls", None)
        additional_kwargs = getattr(message, "additional_kwargs", None)
        if tool_calls:
            continue
        if isinstance(additional_kwargs, dict) and additional_kwargs.get(
            "tool_calls"
        ):
            continue
        sanitized.append(message)
    return sanitized

def _sanitize_checkpoint_state(cls, state: Any) -> _CheckpointRestorePlan:
    if not isinstance(state, dict):
        return _CheckpointRestorePlan(
            messages=[],
            reset_fields=[],
            legacy_fields=[],
            schema_supported=False,
        )

    sanitized_messages = cls._sanitize_checkpoint_messages(state.get("messages"))
    legacy_fields: list[str] = []
    schema_version = state.get("schema_version")
    schema_supported = schema_version == STATE_SCHEMA_V3
    if not schema_supported:
        legacy_fields.append("schema_version")
    raw_messages = state.get("messages")
    if isinstance(raw_messages, list) and len(raw_messages) != len(
        sanitized_messages
    ):
        legacy_fields.append("messages_filtered")
    reset_fields = sorted(
        field for field in _KB_CHAT_CHECKPOINT_RESET_FIELDS if field in state
    )
    return _CheckpointRestorePlan(
        messages=sanitized_messages,
        reset_fields=reset_fields,
        legacy_fields=sorted(set(legacy_fields)),
        schema_supported=schema_supported,
    )

def _build_checkpoint_restore_audit(self, 
    *,
    checkpoint_id: str | None,
    applied: bool,
    reset_fields: list[str],
    legacy_fields: list[str],
    schema_supported: bool,
) -> dict[str, Any]:
    return {
        "checkpoint_restore_applied": bool(applied),
        "checkpoint_restore_source_checkpoint_id": checkpoint_id,
        "checkpoint_restore_reset_fields": sorted(set(reset_fields)),
        "checkpoint_restore_legacy_fields": sorted(set(legacy_fields)),
        "checkpoint_restore_schema_supported": bool(schema_supported),
    }

def _resolve_kb_chat_user_id(self, session: ChatSession) -> str:
    return resolve_kb_chat_store_user_id(
        user_id=getattr(session, "user_id", None),
        thread_id=str(session.id),
    )

async def _get_running_kb_chat_run(
    self,
    *,
    session_id: uuid.UUID,
    exclude_run_id: uuid.UUID | None = None,
) -> AgentRun | None:
    stmt = select(AgentRun).where(
        AgentRun.session_id == session_id,
        AgentRun.run_type == AgentRunType.KB_ANSWER,
        AgentRun.status == AgentRunStatus.RUNNING,
    )
    if exclude_run_id is not None:
        stmt = stmt.where(AgentRun.id != exclude_run_id)
    stmt = stmt.order_by(AgentRun.created_at.desc()).limit(1)
    result = await self._db.execute(stmt)
    return result.scalars().first()

async def _ensure_no_running_kb_chat_run(self, *, session_id: uuid.UUID) -> None:
    await self._db.execute(
        select(ChatSession.id).where(ChatSession.id == session_id).with_for_update()
    )
    running = await self._get_running_kb_chat_run(session_id=session_id)
    if running is None:
        return
    raise AppError(
        code="CHAT_RUN_CONFLICT",
        message="当前会话已有运行中的知识库问答任务，请先完成澄清或等待结束",
        status_code=409,
        details={"run_id": str(running.id)},
    )

async def _ensure_kb_chat_resume_target_valid(
    self,
    *,
    session: ChatSession,
    run: AgentRun,
) -> None:
    await self._db.execute(
        select(ChatSession.id).where(ChatSession.id == session.id).with_for_update()
    )
    running = await self._get_running_kb_chat_run(session_id=session.id)
    if running is None:
        raise AppError(
            code="CHAT_RUN_NOT_RUNNING",
            message="运行记录已完成或已失败",
            status_code=400,
        )
    if running.id != run.id:
        raise AppError(
            code="CHAT_RUN_CONFLICT",
            message="当前会话已有其他运行中的知识库问答任务",
            status_code=409,
            details={"run_id": str(running.id)},
        )

async def _prepare_kb_chat_execution(
    self,
    *,
    session: ChatSession,
    user_content: str,
    run: AgentRun | None = None,
) -> _KbChatExecution:
    resume_requested = run is not None
    started_at = (
        run.started_at if run and run.started_at else datetime.now(timezone.utc)
    )
    thread_id = str(session.id)
    checkpoint_tuple = await CheckpointManager.get_state(thread_id)
    checkpoint_restore = _CheckpointRestorePlan(
        messages=[],
        reset_fields=[],
        legacy_fields=[],
        schema_supported=False,
    )
    checkpoint_id: str | None = None
    if checkpoint_tuple is not None:
        raw_values = (checkpoint_tuple.checkpoint or {}).get("channel_values", {})
        checkpoint_restore = self._sanitize_checkpoint_state(raw_values)
        raw_checkpoint_id = (checkpoint_tuple.checkpoint or {}).get("id")
        checkpoint_id = (
            str(raw_checkpoint_id) if isinstance(raw_checkpoint_id, str) else None
        )

    use_checkpoint_messages = (
        run is not None
        and checkpoint_tuple is not None
        and checkpoint_restore.schema_supported
        and bool(checkpoint_restore.messages)
    )

    summary = None
    history: list[LLMMessage] = []
    history_usage: dict[str, Any] = {}
    history_truncation: dict[str, Any] = {}
    if not use_checkpoint_messages:
        summary = await self._summary_service.load_latest_summary(session.id)
        history = await self._load_history(
            session.id, limit=self._settings.context_history_max_messages
        )

        history_messages, history_usage, history_truncation = (
            self._context_builder.build_history_messages(
                history=history,
                summary_text=summary.content if summary else None,
            )
        )
    else:
        if checkpoint_tuple is not None and run is None:
            logger.warning(
                "KB Chat fresh turn ignored checkpoint messages and rebuilt context from DB history",
                extra={
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                },
            )
        history_messages = []

    # 保存用户消息
    user_msg = ChatMessage(
        session_id=session.id,
        role=MessageRole.USER,
        content=user_content,
    )
    self._db.add(user_msg)

    # 创建或复用运行记录
    if run is None:
        run = AgentRun(
            run_type=AgentRunType.KB_ANSWER,
            session_id=session.id,
            question=user_content,
            selected_kb_ids=session.selected_kb_ids,
            allow_external=session.allow_external,
            mode=session.mode,
            status=AgentRunStatus.RUNNING,
            started_at=started_at,
        )
        self._db.add(run)
    else:
        if run.started_at is None:
            run.started_at = started_at
        run.status = AgentRunStatus.RUNNING
        run.finished_at = None
        run.error_message = None
        run.final_output = None

    await self._db.flush()
    await self._db.commit()
    set_run_id(str(run.id))

    kb_ids = session.selected_kb_ids or []
    default_kb_ids = [uuid.UUID(str(kid)) for kid in kb_ids]
    kb_chat_config = self._resolve_session_kb_chat_config(session)
    kb_chat_config, rollback_note = await self._apply_gray_release_rollback_policy(
        kb_chat_config=kb_chat_config
    )
    retrieval_overrides = self._to_retrieval_overrides(kb_chat_config)

    # kb_retrieve：通过回调收集检索结果（用于 Evidence 落库/指标）
    retrieval_results: list = []
    seen_chunk_ids: set[uuid.UUID] = set()
    retrieval_meta: dict[str, Any] = {
        "usage": None,
        "truncation": None,
        "kb_scope": None,
        "retrieval_round": None,
    }
    retrieval_buffer = _KbRetrievalBuffer(
        results=retrieval_results,
        meta=retrieval_meta,
    )

    def _on_results(included: list, meta: dict[str, Any]) -> None:
        for r in included:
            chunk_id = getattr(getattr(r, "chunk", None), "id", None)
            if chunk_id and chunk_id not in seen_chunk_ids:
                retrieval_results.append(r)
                seen_chunk_ids.add(chunk_id)
        retrieval_meta["usage"] = (
            meta.get("usage") if isinstance(meta.get("usage"), dict) else None
        )
        retrieval_meta["truncation"] = (
            meta.get("truncation")
            if isinstance(meta.get("truncation"), dict)
            else None
        )
        kb_scope = meta.get("kb_scope")
        if isinstance(kb_scope, dict):
            retrieval_meta["kb_scope"] = kb_scope

        raw_round = meta.get("retrieval_round")
        retrieval_round = self._safe_non_negative_int(raw_round)
        if retrieval_round is None:
            retrieval_round = 0
        retrieval_meta["retrieval_round"] = retrieval_round

    kb_tool = build_kb_retrieve_tool(
        retrieval=self._retrieval,
        default_kb_ids=default_kb_ids,
        retrieval_overrides=retrieval_overrides,
        context_builder=self._context_builder,
        on_results=_on_results,
    )

    include_mcp = False  # KB Chat invariant: no MCP/tool-approval flow.
    tools, tool_meta_by_name = await build_tool_registry(
        settings=self._settings,
        extensions=None,
        extra_tools=[kb_tool],
        include_web_search=False,
        include_mcp=include_mcp,
    )

    chat_model = create_chat_model(
        settings=self._settings,
        use_previous_response_id=False,
    )

    system_prompt = self._prompts.render_with_few_shot("kb_chat/system")
    context_metrics = self._context_builder.build_metrics(
        history_usage=history_usage,
        history_truncation=history_truncation,
    )
    resolved_user_id = self._resolve_kb_chat_user_id(session)
    reset_fields = list(checkpoint_restore.reset_fields)
    if (
        checkpoint_tuple is not None
        and not use_checkpoint_messages
        and checkpoint_restore.messages
    ):
        reset_fields.append("messages")
    checkpoint_restore_audit = self._build_checkpoint_restore_audit(
        checkpoint_id=checkpoint_id,
        applied=use_checkpoint_messages,
        reset_fields=reset_fields,
        legacy_fields=checkpoint_restore.legacy_fields,
        schema_supported=checkpoint_restore.schema_supported,
    )

    messages: list[SystemMessage | HumanMessage | AIMessage] = []
    if use_checkpoint_messages:
        messages.extend(checkpoint_restore.messages)
    else:
        messages.append(SystemMessage(content=system_prompt))
    if history_messages:
        messages.extend([self._to_langchain_message(m) for m in history_messages])
    messages.append(HumanMessage(content=user_content))

    graph = self._build_graph(
        chat_model=chat_model,
        tools=tools,
        tool_meta_by_name=tool_meta_by_name,
        kb_chat_config=kb_chat_config,
    )
    from app.agents.kb_chat_agentic_state import make_initial_state

    runtime_config_payload = kb_chat_config.model_dump(mode="json")
    selected_kb_ids = [str(kid) for kid in (session.selected_kb_ids or [])]
    initial_messages: list[AnyMessage] = list(messages)
    state = make_initial_state(
        user_input=user_content,
        messages=initial_messages,
    )
    stage_summaries: dict[str, Any] = {}
    if checkpoint_tuple is not None:
        stage_summaries["checkpoint_restore"] = checkpoint_restore_audit
    if isinstance(rollback_note, dict):
        stage_summaries["gray_release_auto_rollback"] = rollback_note
    state["stage_summaries"] = stage_summaries
    state["metrics"] = {
        "context": context_metrics,
        "checkpoint_restore": checkpoint_restore_audit,
    }
    run_context = graph.make_run_context(
        thread_id=thread_id,
        state=dict(state),
        user_id=resolved_user_id,
        kb_ids=selected_kb_ids,
        runtime_config=runtime_config_payload,
    )
    try:
        store = StoreManager.get_store()
    except Exception:
        store = None
    compiled_graph = graph.compile(
        checkpointer=CheckpointManager.get_checkpointer(),
        store=store,
    )

    return _KbChatExecution(
        started_at=started_at,
        thread_id=thread_id,
        run=run,
        kb_chat_config=kb_chat_config,
        history_usage=history_usage,
        history_truncation=history_truncation,
        retrieval_results=retrieval_results,
        retrieval_meta=retrieval_meta,
        retrieval_buffer=retrieval_buffer,
        graph=graph,
        compiled_graph=compiled_graph,
        state=state,
        run_context=run_context,
        resume_checkpoint_id=(
            str(run.id)
            if resume_requested and getattr(run, "id", None) is not None
            else None
        ),
    )
"""对话接口。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, delete, func, select

from app.api.sse import SSE_HEADERS, encode_sse

from app.api.deps import AsyncSessionDep
from app.core.checkpoint import CheckpointManager
from app.core.errors import AppError, bad_request, not_found
from app.core.settings import get_settings
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession, ChatSessionType
from app.models.evaluation_run import EvaluationRun
from app.models.export_job import ExportJob
from app.models.knowledge_base import KnowledgeBaseReadiness, KnowledgeBaseStatus
from app.schemas.chats import (
    ChatAnswerResponse,
    KbGraphSchemaResponse,
    ChatPendingToolApprovalResponse,
    ChatPendingUserClarificationResponse,
    ClarificationResumeRequest,
    ChatMessageCreate,
    ChatMessageRead,
    ChatRecentListResponse,
    ChatSessionCreate,
    ChatSessionRecentRead,
    ChatSessionRead,
    resolve_kb_chat_config,
    ToolApprovalRequest,
)
from app.services.general_chat_service import GeneralChatService
from app.services.kb_chat_service import KbChatService
from app.services.knowledge_base_service import KnowledgeBaseService

router = APIRouter()


@router.get("/kb-graph-schema", response_model=KbGraphSchemaResponse)
async def get_kb_chat_graph_schema(
    db: AsyncSessionDep,
    request: Request,
    query_rewrite_enabled: bool | None = Query(None),
    ambiguity_check_enabled: bool | None = Query(None),
    hyde_enabled: bool | None = Query(None),
    hybrid_retrieval_enabled: bool | None = Query(None),
    rerank_enabled: bool | None = Query(None),
    retrieval_top_k: int | None = Query(None, ge=1, le=20),
    retrieval_rerank_top_k: int | None = Query(None, ge=1, le=50),
    retrieval_hybrid_ranker: str | None = Query(None, pattern="^(rrf|weighted)$"),
    retrieval_hybrid_dense_weight: float | None = Query(None, ge=0.0, le=1.0),
    retrieval_hybrid_sparse_weight: float | None = Query(None, ge=0.0, le=1.0),
    retrieval_hybrid_rrf_k: int | None = Query(None, ge=1, le=200),
    retrieval_parent_max_parents: int | None = Query(None, ge=1, le=20),
    retrieval_parent_max_children_per_parent: int | None = Query(None, ge=1, le=10),
    retrieval_multiscale_per_window_top_k: int | None = Query(None, ge=1, le=200),
    retrieval_multiscale_rrf_k: int | None = Query(None, ge=1, le=200),
    retrieval_multiscale_max_documents: int | None = Query(None, ge=1, le=100),
    retrieval_multiscale_max_chunks_per_document: int | None = Query(None, ge=1, le=20),
) -> KbGraphSchemaResponse:
    """返回 KB Chat 的 LangGraph 节点/边结构（含节点 metadata）。"""
    raw_config = {
        key: value
        for key, value in {
            "query_rewrite_enabled": query_rewrite_enabled,
            "ambiguity_check_enabled": ambiguity_check_enabled,
            "hyde_enabled": hyde_enabled,
            "hybrid_retrieval_enabled": hybrid_retrieval_enabled,
            "rerank_enabled": rerank_enabled,
            "retrieval_top_k": retrieval_top_k,
            "retrieval_rerank_top_k": retrieval_rerank_top_k,
            "retrieval_hybrid_ranker": retrieval_hybrid_ranker,
            "retrieval_hybrid_dense_weight": retrieval_hybrid_dense_weight,
            "retrieval_hybrid_sparse_weight": retrieval_hybrid_sparse_weight,
            "retrieval_hybrid_rrf_k": retrieval_hybrid_rrf_k,
            "retrieval_parent_max_parents": retrieval_parent_max_parents,
            "retrieval_parent_max_children_per_parent": retrieval_parent_max_children_per_parent,
            "retrieval_multiscale_per_window_top_k": retrieval_multiscale_per_window_top_k,
            "retrieval_multiscale_rrf_k": retrieval_multiscale_rrf_k,
            "retrieval_multiscale_max_documents": retrieval_multiscale_max_documents,
            "retrieval_multiscale_max_chunks_per_document": retrieval_multiscale_max_chunks_per_document,
        }.items()
        if value is not None
    }
    resolved = resolve_kb_chat_config(raw=raw_config or None, settings=get_settings())
    service = KbChatService(
        db,
        request.app.state.llm_client,
        request.app.state.milvus_client,
        request.app.state.embedding_client,
        reranker=request.app.state.rerank_client,
        redis=request.app.state.redis,
    )
    schema = await service.get_graph_schema(kb_chat_config=resolved)
    return KbGraphSchemaResponse.model_validate(schema)


@router.post("", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
async def create_chat_session(
    db: AsyncSessionDep,
    body: ChatSessionCreate,
) -> ChatSessionRead:
    """创建会话。"""
    settings = get_settings()

    if body.session_type == ChatSessionType.KB_CHAT and not body.selected_kb_ids:
        raise bad_request(
            code="CHAT_MISSING_KB_IDS",
            message="kb_chat 类型必须选择至少一个知识库",
        )

    if body.session_type == ChatSessionType.KB_CHAT:
        kb_service = KnowledgeBaseService(db)
        kb_ids = body.selected_kb_ids or []
        kbs = await kb_service.get_by_ids(kb_ids)
        if len(kbs) != len(kb_ids):
            raise bad_request(code="KB_NOT_FOUND", message="存在不存在的知识库")

        not_selectable = [
            str(kb.id)
            for kb in kbs
            if kb.status != KnowledgeBaseStatus.ACTIVE
            or kb.readiness != KnowledgeBaseReadiness.READY
        ]
        if not_selectable:
            raise bad_request(
                code="KB_NOT_SELECTABLE",
                message="所选知识库尚不可用于业务入口",
                details={"kb_ids": not_selectable},
            )
    elif body.kb_chat_config is not None:
        raise bad_request(
            code="CHAT_KB_CONFIG_UNSUPPORTED",
            message="仅 kb_chat 会话支持 kb_chat_config",
        )

    kb_chat_config_json = None
    if body.session_type == ChatSessionType.KB_CHAT:
        resolved = resolve_kb_chat_config(
            raw=body.kb_chat_config,
            settings=settings,
        )
        kb_chat_config_json = resolved.model_dump(mode="json")

    session = ChatSession(
        session_type=body.session_type,
        selected_kb_ids=body.selected_kb_ids,
        allow_external=body.allow_external,
        mode=body.mode,
        kb_chat_config=kb_chat_config_json,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return ChatSessionRead.model_validate(session)


@router.get("/recent", response_model=ChatRecentListResponse)
async def list_recent_chats(
    db: AsyncSessionDep,
    limit: int = Query(20, ge=1, le=100),
) -> ChatRecentListResponse:
    """获取最近对话列表。"""
    settings = get_settings()
    web_search_available = bool(settings.web_search_api_key)

    latest_message_subq = (
        select(
            ChatMessage.session_id.label("session_id"),
            func.max(ChatMessage.created_at).label("last_message_at"),
        )
        .where(ChatMessage.role.in_([MessageRole.USER, MessageRole.ASSISTANT]))
        .group_by(ChatMessage.session_id)
        .subquery()
    )

    latest_user_message_subq = (
        select(
            ChatMessage.session_id.label("session_id"),
            ChatMessage.content.label("content"),
            func.row_number()
            .over(
                partition_by=ChatMessage.session_id,
                order_by=ChatMessage.created_at.desc(),
            )
            .label("rn"),
        )
        .where(ChatMessage.role == MessageRole.USER)
        .subquery()
    )

    stmt = (
        select(
            ChatSession,
            latest_message_subq.c.last_message_at,
            latest_user_message_subq.c.content,
        )
        .join(latest_message_subq, latest_message_subq.c.session_id == ChatSession.id)
        .outerjoin(
            latest_user_message_subq,
            and_(
                latest_user_message_subq.c.session_id == ChatSession.id,
                latest_user_message_subq.c.rn == 1,
            ),
        )
        .order_by(latest_message_subq.c.last_message_at.desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    items: list[ChatSessionRecentRead] = []
    for session, last_message_at, last_user_content in result.all():
        title = session.title or (
            (last_user_content[:30] if last_user_content else None)
        )
        items.append(
            ChatSessionRecentRead(
                id=session.id,
                session_type=session.session_type,
                title=title,
                updated_at=last_message_at or session.updated_at,
            )
        )

    return ChatRecentListResponse(
        items=items,
        web_search_available=web_search_available,
    )


@router.get("/{session_id}", response_model=ChatSessionRead)
async def get_chat_session(
    db: AsyncSessionDep,
    session_id: uuid.UUID,
) -> ChatSessionRead:
    """获取会话详情。"""
    session = await db.get(ChatSession, session_id)
    if not session:
        raise not_found("会话不存在", code="CHAT_SESSION_NOT_FOUND")
    return ChatSessionRead.model_validate(session)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    db: AsyncSessionDep,
    session_id: uuid.UUID,
) -> None:
    """删除会话。"""
    session = await db.get(ChatSession, session_id)
    if not session:
        raise not_found("会话不存在", code="CHAT_SESSION_NOT_FOUND")
    try:
        await CheckpointManager.delete_thread(str(session_id))
    except Exception as exc:
        raise AppError(
            code="CHAT_CHECKPOINT_DELETE_FAILED",
            message="删除会话检查点失败",
            status_code=500,
            details={"reason": str(exc)},
        )

    run_ids_result = await db.execute(
        select(AgentRun.id).where(AgentRun.session_id == session_id)
    )
    run_ids = [row[0] for row in run_ids_result.all()]

    eval_ids: list[uuid.UUID] = []
    eval_ids_result = await db.execute(
        select(EvaluationRun.id).where(
            EvaluationRun.related_session_ids.any(session_id)
        )
    )
    eval_ids = [row[0] for row in eval_ids_result.all()]

    export_run_ids = list({*run_ids, *eval_ids})
    if export_run_ids:
        await db.execute(delete(ExportJob).where(ExportJob.run_id.in_(export_run_ids)))

    if eval_ids:
        await db.execute(delete(EvaluationRun).where(EvaluationRun.id.in_(eval_ids)))

    await db.execute(delete(AgentRun).where(AgentRun.session_id == session_id))
    await db.delete(session)
    await db.commit()
    return None


@router.get("/{session_id}/messages", response_model=list[ChatMessageRead])
async def get_chat_messages(
    db: AsyncSessionDep,
    session_id: uuid.UUID,
) -> list[ChatMessageRead]:
    """获取会话消息（仅返回 HumanMessage/AIMessage）。"""
    session = await db.get(ChatSession, session_id)
    if not session:
        raise not_found("会话不存在", code="CHAT_SESSION_NOT_FOUND")

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role.in_([MessageRole.USER, MessageRole.ASSISTANT]))
        .order_by(ChatMessage.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = [
        ChatMessageRead.model_validate(msg)
        for msg in result.scalars().all()
        if not (msg.meta or {}).get("summary")
    ]
    return messages


@router.post(
    "/{session_id}/messages",
    response_model=(
        ChatAnswerResponse
        | ChatPendingToolApprovalResponse
        | ChatPendingUserClarificationResponse
    ),
)
async def create_chat_message(
    db: AsyncSessionDep,
    request: Request,
    response: Response,
    session_id: uuid.UUID,
    body: ChatMessageCreate,
) -> (
    ChatAnswerResponse | ChatPendingToolApprovalResponse | ChatPendingUserClarificationResponse
):
    """发送消息并获得回答。"""
    session = await db.get(ChatSession, session_id)
    if not session:
        raise not_found("会话不存在", code="CHAT_SESSION_NOT_FOUND")

    llm = request.app.state.llm_client

    if session.session_type == ChatSessionType.KB_CHAT:
        # 知识库问答
        milvus = request.app.state.milvus_client
        embedding = request.app.state.embedding_client
        reranker = request.app.state.rerank_client
        redis = request.app.state.redis
        service = KbChatService(
            db, llm, milvus, embedding, reranker=reranker, redis=redis
        )
        result = await service.answer(session=session, user_content=body.content)
    elif session.session_type == ChatSessionType.GENERAL_CHAT:
        # 普通代理
        service = GeneralChatService(
            db,
            llm,
            redis=request.app.state.redis,
            http_client=request.app.state.http_client,
        )
        result = await service.answer(session=session, user_content=body.content)
    else:
        raise bad_request(code="CHAT_UNSUPPORTED_SESSION_TYPE", message="不支持的会话类型")

    if getattr(result, "status", None) in {
        "pending_tool_approval",
        "pending_user_clarification",
    }:
        response.status_code = status.HTTP_202_ACCEPTED
    return result


@router.post("/{session_id}/messages/stream")
async def create_chat_message_stream(
    db: AsyncSessionDep,
    request: Request,
    session_id: uuid.UUID,
    body: ChatMessageCreate,
):
    """发送消息并获得流式回答。"""
    session = await db.get(ChatSession, session_id)
    if not session:
        raise not_found("会话不存在", code="CHAT_SESSION_NOT_FOUND")

    llm = request.app.state.llm_client

    if session.session_type == ChatSessionType.KB_CHAT:
        milvus = request.app.state.milvus_client
        embedding = request.app.state.embedding_client
        reranker = request.app.state.rerank_client
        redis = request.app.state.redis
        service = KbChatService(
            db, llm, milvus, embedding, reranker=reranker, redis=redis
        )
        events = service.answer_stream(
            session=session,
            user_content=body.content,
            request=request,
        )
    elif session.session_type == ChatSessionType.GENERAL_CHAT:
        service = GeneralChatService(
            db,
            llm,
            redis=request.app.state.redis,
            http_client=request.app.state.http_client,
        )
        events = service.answer_stream(
            session=session,
            user_content=body.content,
            request=request,
        )
    else:
        raise bad_request(code="CHAT_UNSUPPORTED_SESSION_TYPE", message="不支持的会话类型")

    return StreamingResponse(
        encode_sse(events),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post(
    "/{session_id}/runs/{run_id}/resume",
    response_model=ChatAnswerResponse | ChatPendingToolApprovalResponse,
)
async def resume_general_chat(
    db: AsyncSessionDep,
    request: Request,
    response: Response,
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    body: ToolApprovalRequest,
) -> ChatAnswerResponse | ChatPendingToolApprovalResponse:
    """两阶段交互：提交工具审批结果并恢复执行。"""
    session = await db.get(ChatSession, session_id)
    if not session:
        raise not_found("会话不存在", code="CHAT_SESSION_NOT_FOUND")
    if session.session_type != ChatSessionType.GENERAL_CHAT:
        raise bad_request(code="CHAT_NOT_GENERAL_CHAT", message="仅普通代理支持恢复执行")

    run = await db.get(AgentRun, run_id)
    if not run or run.session_id != session.id:
        raise not_found("运行记录不存在", code="CHAT_RUN_NOT_FOUND")
    if run.run_type != AgentRunType.GENERAL_ANSWER:
        raise bad_request(code="CHAT_RUN_TYPE_MISMATCH", message="运行记录类型不匹配")
    if run.status != AgentRunStatus.RUNNING:
        raise bad_request(code="CHAT_RUN_NOT_RUNNING", message="运行记录已完成或已失败")
    llm = request.app.state.llm_client
    service = GeneralChatService(
        db,
        llm,
        redis=request.app.state.redis,
        http_client=request.app.state.http_client,
    )
    result = await service.resume_after_tool_approval(
        session=session, run=run, approved=body.approved
    )
    if getattr(result, "status", None) == "pending_tool_approval":
        response.status_code = status.HTTP_202_ACCEPTED
    return result


@router.post(
    "/{session_id}/runs/{run_id}/clarification",
    response_model=ChatAnswerResponse | ChatPendingUserClarificationResponse,
)
async def resume_kb_chat_after_clarification(
    db: AsyncSessionDep,
    request: Request,
    response: Response,
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    body: ClarificationResumeRequest,
) -> ChatAnswerResponse | ChatPendingUserClarificationResponse:
    """提交澄清信息并恢复 KB Chat 执行。"""
    session = await db.get(ChatSession, session_id)
    if not session:
        raise not_found("会话不存在", code="CHAT_SESSION_NOT_FOUND")
    if session.session_type != ChatSessionType.KB_CHAT:
        raise bad_request(code="CHAT_NOT_KB_CHAT", message="仅知识库会话支持该恢复接口")

    run = await db.get(AgentRun, run_id)
    if not run or run.session_id != session.id:
        raise not_found("运行记录不存在", code="CHAT_RUN_NOT_FOUND")
    if run.run_type != AgentRunType.KB_ANSWER:
        raise bad_request(code="CHAT_RUN_TYPE_MISMATCH", message="运行记录类型不匹配")
    if run.status != AgentRunStatus.RUNNING:
        raise bad_request(code="CHAT_RUN_NOT_RUNNING", message="运行记录已完成或已失败")
    clarification_pending = (
        run.stage_summaries.get("clarification_pending")
        if isinstance(run.stage_summaries, dict)
        else None
    )
    if not (
        isinstance(clarification_pending, dict)
        and clarification_pending.get("pending") is True
    ):
        raise bad_request(
            code="CHAT_NO_PENDING_CLARIFICATION",
            message="当前运行没有待补充澄清信息",
        )

    llm = request.app.state.llm_client
    service = KbChatService(
        db,
        llm,
        request.app.state.milvus_client,
        request.app.state.embedding_client,
        reranker=request.app.state.rerank_client,
        redis=request.app.state.redis,
    )
    result = await service.answer(
        session=session,
        user_content=body.content,
        run=run,
    )
    if getattr(result, "status", None) == "pending_user_clarification":
        response.status_code = status.HTTP_202_ACCEPTED
    return result


@router.post("/{session_id}/runs/{run_id}/clarification/stream")
async def resume_kb_chat_after_clarification_stream(
    db: AsyncSessionDep,
    request: Request,
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    body: ClarificationResumeRequest,
):
    """提交澄清信息并恢复 KB Chat 执行（流式）。"""
    session = await db.get(ChatSession, session_id)
    if not session:
        raise not_found("会话不存在", code="CHAT_SESSION_NOT_FOUND")
    if session.session_type != ChatSessionType.KB_CHAT:
        raise bad_request(code="CHAT_NOT_KB_CHAT", message="仅知识库会话支持该恢复接口")

    run = await db.get(AgentRun, run_id)
    if not run or run.session_id != session.id:
        raise not_found("运行记录不存在", code="CHAT_RUN_NOT_FOUND")
    if run.run_type != AgentRunType.KB_ANSWER:
        raise bad_request(code="CHAT_RUN_TYPE_MISMATCH", message="运行记录类型不匹配")
    if run.status != AgentRunStatus.RUNNING:
        raise bad_request(code="CHAT_RUN_NOT_RUNNING", message="运行记录已完成或已失败")
    clarification_pending = (
        run.stage_summaries.get("clarification_pending")
        if isinstance(run.stage_summaries, dict)
        else None
    )
    if not (
        isinstance(clarification_pending, dict)
        and clarification_pending.get("pending") is True
    ):
        raise bad_request(
            code="CHAT_NO_PENDING_CLARIFICATION",
            message="当前运行没有待补充澄清信息",
        )

    llm = request.app.state.llm_client
    service = KbChatService(
        db,
        llm,
        request.app.state.milvus_client,
        request.app.state.embedding_client,
        reranker=request.app.state.rerank_client,
        redis=request.app.state.redis,
    )
    events = service.answer_stream(
        session=session,
        user_content=body.content,
        request=request,
        run=run,
    )

    return StreamingResponse(
        encode_sse(events),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/{session_id}/runs/{run_id}/resume/stream")
async def resume_general_chat_stream(
    db: AsyncSessionDep,
    request: Request,
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    body: ToolApprovalRequest,
):
    """两阶段交互：提交工具审批结果并恢复执行（流式）。"""
    session = await db.get(ChatSession, session_id)
    if not session:
        raise not_found("会话不存在", code="CHAT_SESSION_NOT_FOUND")
    if session.session_type != ChatSessionType.GENERAL_CHAT:
        raise bad_request(code="CHAT_NOT_GENERAL_CHAT", message="仅普通代理支持恢复执行")

    run = await db.get(AgentRun, run_id)
    if not run or run.session_id != session.id:
        raise not_found("运行记录不存在", code="CHAT_RUN_NOT_FOUND")
    if run.run_type != AgentRunType.GENERAL_ANSWER:
        raise bad_request(code="CHAT_RUN_TYPE_MISMATCH", message="运行记录类型不匹配")
    if run.status != AgentRunStatus.RUNNING:
        raise bad_request(code="CHAT_RUN_NOT_RUNNING", message="运行记录已完成或已失败")

    llm = request.app.state.llm_client
    service = GeneralChatService(
        db,
        llm,
        redis=request.app.state.redis,
        http_client=request.app.state.http_client,
    )
    events = service.resume_after_tool_approval_stream(
        session=session,
        run=run,
        approved=body.approved,
        request=request,
    )

    return StreamingResponse(
        encode_sse(events),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )

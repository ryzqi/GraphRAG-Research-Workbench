"""对话接口。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.sse import SSE_HEADERS, encode_sse

from app.api.deps import AsyncSessionDep, CurrentUserDep
from app.core.errors import bad_request, not_found
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_session import ChatSession, ChatSessionType
from app.schemas.chats import (
    ChatAnswerResponse,
    ChatPendingToolApprovalResponse,
    ChatMessageCreate,
    ChatSessionCreate,
    ChatSessionRead,
    ToolApprovalRequest,
)
from app.services.general_chat_service import GeneralChatService
from app.services.kb_chat_service import KbChatService

router = APIRouter()


@router.post("", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
async def create_chat_session(
    db: AsyncSessionDep,
    _user: CurrentUserDep,
    body: ChatSessionCreate,
) -> ChatSessionRead:
    """创建会话。"""
    # kb_chat 必须选择知识库
    if body.session_type == ChatSessionType.KB_CHAT and not body.selected_kb_ids:
        raise bad_request(
            code="CHAT_MISSING_KB_IDS",
            message="kb_chat 类型必须选择至少一个知识库",
        )

    session = ChatSession(
        session_type=body.session_type,
        selected_kb_ids=body.selected_kb_ids,
        allow_external=body.allow_external,
        mode=body.mode,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return ChatSessionRead.model_validate(session)


@router.get("/{session_id}", response_model=ChatSessionRead)
async def get_chat_session(
    db: AsyncSessionDep,
    _user: CurrentUserDep,
    session_id: uuid.UUID,
) -> ChatSessionRead:
    """获取会话详情。"""
    session = await db.get(ChatSession, session_id)
    if not session:
        raise not_found("会话不存在", code="CHAT_SESSION_NOT_FOUND")
    return ChatSessionRead.model_validate(session)


@router.post(
    "/{session_id}/messages",
    response_model=ChatAnswerResponse | ChatPendingToolApprovalResponse,
)
async def create_chat_message(
    db: AsyncSessionDep,
    _user: CurrentUserDep,
    request: Request,
    response: Response,
    session_id: uuid.UUID,
    body: ChatMessageCreate,
) -> ChatAnswerResponse | ChatPendingToolApprovalResponse:
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
        service = KbChatService(db, llm, milvus, embedding, reranker=reranker)
        return await service.answer(session=session, user_content=body.content)

    elif session.session_type == ChatSessionType.GENERAL_CHAT:
        # 全能代理
        mcp = request.app.state.mcp_client
        service = GeneralChatService(db, llm, mcp)
        result = await service.answer(session=session, user_content=body.content)
        if getattr(result, "status", None) == "pending_tool_approval":
            response.status_code = status.HTTP_202_ACCEPTED
        return result

    else:
        raise bad_request(code="CHAT_UNSUPPORTED_SESSION_TYPE", message="不支持的会话类型")


@router.post("/{session_id}/messages/stream")
async def create_chat_message_stream(
    db: AsyncSessionDep,
    _user: CurrentUserDep,
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
        service = KbChatService(db, llm, milvus, embedding, reranker=reranker)
        events = service.answer_stream(
            session=session,
            user_content=body.content,
            request=request,
        )
    elif session.session_type == ChatSessionType.GENERAL_CHAT:
        mcp = request.app.state.mcp_client
        service = GeneralChatService(db, llm, mcp)
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
    _user: CurrentUserDep,
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
        raise bad_request(code="CHAT_NOT_GENERAL_CHAT", message="仅全能代理支持恢复执行")

    run = await db.get(AgentRun, run_id)
    if not run or run.session_id != session.id:
        raise not_found("运行记录不存在", code="CHAT_RUN_NOT_FOUND")
    if run.run_type != AgentRunType.GENERAL_ANSWER:
        raise bad_request(code="CHAT_RUN_TYPE_MISMATCH", message="运行记录类型不匹配")
    if run.status != AgentRunStatus.RUNNING:
        raise bad_request(code="CHAT_RUN_NOT_RUNNING", message="运行记录已完成或已失败")

    llm = request.app.state.llm_client
    mcp = request.app.state.mcp_client
    service = GeneralChatService(db, llm, mcp)
    result = await service.resume_after_tool_approval(
        session=session, run=run, approved=body.approved
    )
    if getattr(result, "status", None) == "pending_tool_approval":
        response.status_code = status.HTTP_202_ACCEPTED
    return result


@router.post("/{session_id}/runs/{run_id}/resume/stream")
async def resume_general_chat_stream(
    db: AsyncSessionDep,
    _user: CurrentUserDep,
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
        raise bad_request(code="CHAT_NOT_GENERAL_CHAT", message="仅全能代理支持恢复执行")

    run = await db.get(AgentRun, run_id)
    if not run or run.session_id != session.id:
        raise not_found("运行记录不存在", code="CHAT_RUN_NOT_FOUND")
    if run.run_type != AgentRunType.GENERAL_ANSWER:
        raise bad_request(code="CHAT_RUN_TYPE_MISMATCH", message="运行记录类型不匹配")
    if run.status != AgentRunStatus.RUNNING:
        raise bad_request(code="CHAT_RUN_NOT_RUNNING", message="运行记录已完成或已失败")

    llm = request.app.state.llm_client
    mcp = request.app.state.mcp_client
    service = GeneralChatService(db, llm, mcp)
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

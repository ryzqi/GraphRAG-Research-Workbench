"""对话接口。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import AsyncSessionDep, CurrentUserDep
from app.core.errors import bad_request, not_found
from app.models.chat_session import ChatSession, ChatSessionType
from app.schemas.chats import (
    ChatAnswerResponse,
    ChatMessageCreate,
    ChatSessionCreate,
    ChatSessionRead,
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


@router.post("/{session_id}/messages", response_model=ChatAnswerResponse)
async def create_chat_message(
    db: AsyncSessionDep,
    _user: CurrentUserDep,
    request: Request,
    session_id: uuid.UUID,
    body: ChatMessageCreate,
) -> ChatAnswerResponse:
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
        return await service.answer(session=session, user_content=body.content)

    else:
        raise bad_request(code="CHAT_UNSUPPORTED_SESSION_TYPE", message="不支持的会话类型")

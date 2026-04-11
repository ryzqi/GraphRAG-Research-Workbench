from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.general_chat_service import GeneralChatService
from app.services.kb_chat_service import KbChatService


def stream_heartbeat_payload() -> dict[str, str]:
    return {
        "type": "heartbeat",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def build_kb_chat_service(*, db: AsyncSession, request: Request) -> KbChatService:
    return KbChatService(
        db,
        request.app.state.llm_client,
        request.app.state.milvus_client,
        request.app.state.embedding_client,
        reranker=request.app.state.rerank_client,
        redis=request.app.state.redis,
    )


def build_general_chat_service(
    *,
    db: AsyncSession,
    request: Request,
) -> GeneralChatService:
    return GeneralChatService(
        db,
        request.app.state.llm_client,
        redis=request.app.state.redis,
        http_client=request.app.state.http_client,
    )

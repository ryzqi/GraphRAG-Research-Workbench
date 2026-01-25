"""对话摘要服务（滚动摘要，LangMem 优先）。

Summary is stored as a SYSTEM ChatMessage with a meta flag so it can be:
- Loaded into runtime context (as a SystemMessage prefix) on later turns
- Filtered out from normal history rendering
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings, get_settings
from app.integrations.langchain_profiles import build_chat_model_profile
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.models.chat_message import ChatMessage, MessageRole
from app.utils.token_counter import count_tokens_approximately


@dataclass(slots=True)
class SummaryUpdateResult:
    summary_text: str
    stats: dict[str, int]


class ConversationSummaryService:
    """滚动摘要：作为 SYSTEM 消息持久化（meta 标记），用于后续 turn 的上下文压缩。"""

    _META_FLAG = "summary"
    _META_VERSION = 1

    def __init__(
        self,
        db: AsyncSession,
        *,
        settings: Settings | None = None,
        summarizer: Callable[[list[LLMMessage], str | None], Any] | None = None,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        self._db = db
        self._settings = settings or get_settings()
        self._summarizer = summarizer
        self._token_counter = token_counter or count_tokens_approximately

    async def load_latest_summary(self, session_id) -> ChatMessage | None:
        if not self._settings.summary_enabled:
            return None

        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .where(ChatMessage.role == MessageRole.SYSTEM)
            .where(ChatMessage.meta.contains({self._META_FLAG: True}))
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        result = await self._db.execute(stmt)
        return result.scalars().first()

    async def maybe_update_summary(
        self, session_id
    ) -> SummaryUpdateResult | None:
        if not self._settings.summary_enabled:
            return None

        last_summary = await self.load_latest_summary(session_id)
        since = last_summary.created_at if last_summary else None
        messages = await self._load_messages_since(session_id, since)
        if not messages:
            return None

        total_tokens = sum(self._token_counter(m.content) for m in messages)
        if not self._should_update(len(messages), total_tokens):
            return None

        previous_summary = last_summary.content if last_summary else None
        summary_text = await self._summarize(messages, previous_summary)
        if not summary_text:
            return None

        await self._persist_summary(session_id, summary_text)

        return SummaryUpdateResult(
            summary_text=summary_text,
            stats={"message_count": len(messages), "token_count": total_tokens},
        )

    def is_summary_message(self, msg: ChatMessage) -> bool:
        return bool((msg.meta or {}).get(self._META_FLAG))

    async def _persist_summary(self, session_id, summary_text: str) -> None:
        """Persist the latest summary and keep history clean (delete older summaries)."""
        await self._db.execute(
            delete(ChatMessage).where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.SYSTEM,
                ChatMessage.meta.contains({self._META_FLAG: True}),
            )
        )

        self._db.add(
            ChatMessage(
                session_id=session_id,
                role=MessageRole.SYSTEM,
                content=summary_text,
                meta={self._META_FLAG: True, "version": self._META_VERSION},
            )
        )

    async def _load_messages_since(
        self, session_id, since: datetime | None
    ) -> list[LLMMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .where(ChatMessage.role != MessageRole.SYSTEM)
            .order_by(ChatMessage.created_at.asc())
        )
        if since is not None:
            stmt = stmt.where(ChatMessage.created_at > since)
        result = await self._db.execute(stmt)
        return [
            LLMMessage(role=msg.role.value, content=msg.content)
            for msg in result.scalars().all()
        ]

    def _should_update(self, message_count: int, token_count: int) -> bool:
        min_messages = self._settings.summary_trigger_min_messages
        min_tokens = self._settings.summary_trigger_min_tokens

        meets_messages = min_messages > 0 and message_count >= min_messages
        meets_tokens = min_tokens > 0 and token_count >= min_tokens
        return meets_messages or meets_tokens

    async def _summarize(
        self, messages: list[LLMMessage], previous_summary: str | None
    ) -> str | None:
        if self._summarizer is not None:
            result = self._summarizer(messages, previous_summary)
            if inspect.isawaitable(result):
                return await result
            return result
        return await self._summarize_with_langmem(messages, previous_summary)

    async def _summarize_with_langmem(
        self, messages: list[LLMMessage], previous_summary: str | None
    ) -> str | None:
        from langchain.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
        from langmem.short_term import RunningSummary, summarize_messages

        model = ChatOpenAI(
            model=self._settings.llm_model,
            base_url=self._settings.llm_base_url,
            api_key=self._settings.llm_api_key,
            profile=build_chat_model_profile(self._settings),
        )
        summary_model = model.bind(max_tokens=self._settings.summary_max_tokens)
        token_counter = getattr(model, "get_num_tokens_from_messages", None)
        if token_counter is None:
            def token_counter(msgs: list[object]) -> int:
                return sum(
                    count_tokens_approximately(getattr(m, "content", "") or "")
                    for m in msgs
                )

        lc_messages = []
        for msg in messages:
            if msg.role == MessageRole.USER.value:
                lc_messages.append(HumanMessage(content=msg.content))
            elif msg.role == MessageRole.ASSISTANT.value:
                lc_messages.append(AIMessage(content=msg.content))
            else:
                lc_messages.append(SystemMessage(content=msg.content))

        running_summary = None
        if previous_summary:
            try:
                running_summary = RunningSummary(summary=previous_summary)
            except Exception:
                running_summary = None

        def _run() -> object:
            return summarize_messages(
                lc_messages,
                running_summary=running_summary,
                token_counter=token_counter,
                model=summary_model,
                max_tokens=self._settings.summary_max_tokens,
                max_tokens_before_summary=0,
                max_summary_tokens=self._settings.summary_max_tokens,
            )

        result = await asyncio.to_thread(_run)
        summary_text = None
        running = getattr(result, "running_summary", None)
        if running is not None:
            summary_text = getattr(running, "summary", None) or getattr(running, "text", None)

        if not summary_text:
            summary_text = self._extract_summary_from_messages(
                getattr(result, "messages", [])
            )

        if summary_text:
            return summary_text.strip()
        return None

    @staticmethod
    def _extract_summary_from_messages(messages: list[object]) -> str | None:
        if not messages:
            return None
        first = messages[0]
        content = getattr(first, "content", None)
        if isinstance(content, str):
            return content
        return None

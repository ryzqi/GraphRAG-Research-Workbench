import uuid

import pytest

from app.core.settings import Settings
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.models.chat_message import MessageRole
from app.services.conversation_summary_service import ConversationSummaryService


class FakeSession:
    def __init__(self) -> None:
        self.added = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


class DummySummaryService(ConversationSummaryService):
    def __init__(
        self,
        *,
        messages: list[LLMMessage],
        settings: Settings,
        summarizer,
    ) -> None:
        self._fake_db = FakeSession()
        super().__init__(
            db=self._fake_db,
            settings=settings,
            summarizer=summarizer,
        )
        self._messages = messages

    async def load_latest_summary(self, session_id):
        return None

    async def _load_messages_since(self, session_id, since):
        return self._messages


@pytest.mark.asyncio
async def test_summary_disabled_skips_update() -> None:
    settings = Settings(summary_enabled=False)
    service = DummySummaryService(
        messages=[LLMMessage(role="user", content="hi")],
        settings=settings,
        summarizer=lambda *_: "summary",
    )

    result = await service.maybe_update_summary(uuid.uuid4())

    assert result is None
    assert service._fake_db.added == []


@pytest.mark.asyncio
async def test_summary_enabled_persists_summary() -> None:
    settings = Settings(summary_enabled=True, summary_trigger_min_messages=2)
    service = DummySummaryService(
        messages=[
            LLMMessage(role=MessageRole.USER.value, content="hi"),
            LLMMessage(role=MessageRole.ASSISTANT.value, content="ok"),
        ],
        settings=settings,
        summarizer=lambda *_: "summary text",
    )

    result = await service.maybe_update_summary(uuid.uuid4())

    assert result is not None
    assert service._fake_db.added
    assert result.message.meta.get("summary") is True

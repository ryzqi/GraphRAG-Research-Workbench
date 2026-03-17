from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.chats import ChatMessageCreate


def test_chat_message_create_rejects_invisible_only_content() -> None:
    with pytest.raises(ValidationError):
        ChatMessageCreate(content="\u200b")


def test_chat_message_create_accepts_visible_content() -> None:
    payload = ChatMessageCreate(content="请回答问题")

    assert payload.content == "请回答问题"

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.chats import ChatMessageCreate


@pytest.mark.parametrize(
    "content",
    ["\u200b", "\u200e", "\u200f", "\u2066", "\u2069", "\u00ad"],
)
def test_chat_message_create_rejects_invisible_only_content(content: str) -> None:
    with pytest.raises(ValidationError):
        ChatMessageCreate(content=content)


def test_chat_message_create_accepts_visible_content() -> None:
    payload = ChatMessageCreate(content="请回答问题")

    assert payload.content == "请回答问题"

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.chats import KbChatConfig, resolve_kb_chat_config


def test_kb_chat_config_rejects_removed_entity_expand_timeout_field() -> None:
    with pytest.raises(ValidationError):
        KbChatConfig(entity_expand_timeout_seconds=1.2)


def test_resolve_kb_chat_config_rejects_removed_entity_expand_timeout_field() -> None:
    with pytest.raises(ValidationError):
        resolve_kb_chat_config(raw={"entity_expand_timeout_seconds": 1.2})

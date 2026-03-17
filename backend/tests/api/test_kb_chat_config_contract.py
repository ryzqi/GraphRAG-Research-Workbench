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


@pytest.mark.parametrize(
    ("removed_key", "value"),
    [
        ("retrieval_hybrid_ranker", "rrf"),
        ("retrieval_hybrid_dense_weight", 0.7),
        ("retrieval_hybrid_sparse_weight", 0.3),
    ],
)
def test_kb_chat_config_rejects_removed_hybrid_keys(
    removed_key: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        KbChatConfig(**{removed_key: value})


@pytest.mark.parametrize(
    ("removed_key", "value"),
    [
        ("retrieval_hybrid_ranker", "rrf"),
        ("retrieval_hybrid_dense_weight", 0.7),
        ("retrieval_hybrid_sparse_weight", 0.3),
    ],
)
def test_resolve_kb_chat_config_rejects_removed_hybrid_keys(
    removed_key: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        resolve_kb_chat_config(raw={removed_key: value})

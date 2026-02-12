from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.chats import (
    KbChatConfig,
    default_kb_chat_config,
    resolve_kb_chat_config,
)


def _settings_stub(**overrides: bool) -> SimpleNamespace:
    base = {
        "retrieval_query_rewrite_enabled": True,
        "kb_chat_ambiguity_check_enabled": True,
        "kb_chat_decomposition_enabled": False,
        "kb_chat_multi_query_enabled": False,
        "kb_chat_hyde_enabled": False,
        "retrieval_hybrid_enabled": True,
        "retrieval_rerank_enabled": True,
        "kb_chat_force_retrieve": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_kb_chat_config_rejects_decomposition_multi_query_enabled_at_same_time() -> None:
    with pytest.raises(ValidationError):
        KbChatConfig(
            decomposition_enabled=True,
            multi_query_enabled=True,
        )


def test_default_kb_chat_config_reads_values_from_settings() -> None:
    settings = _settings_stub(
        retrieval_query_rewrite_enabled=False,
        kb_chat_hyde_enabled=True,
        retrieval_rerank_enabled=False,
    )

    config = default_kb_chat_config(settings=settings)

    assert config.query_rewrite_enabled is False
    assert config.hyde_enabled is True
    assert config.rerank_enabled is False


def test_resolve_kb_chat_config_merges_partial_payload_with_defaults() -> None:
    settings = _settings_stub(
        kb_chat_hyde_enabled=True,
        retrieval_rerank_enabled=False,
    )

    config = resolve_kb_chat_config(
        raw={
            "multi_query_enabled": True,
            "query_rewrite_enabled": False,
        },
        settings=settings,
    )

    assert config.multi_query_enabled is True
    assert config.query_rewrite_enabled is False
    assert config.hyde_enabled is True
    assert config.rerank_enabled is False

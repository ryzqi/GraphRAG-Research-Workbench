from __future__ import annotations

from app.models.model_config import ModelProvider
from app.services.chat_replay_policy import ReplayMode, decide_replay_mode


def test_auto_mode_prefers_response_id_for_openai_thinking() -> None:
    decision = decide_replay_mode(
        configured_mode="auto",
        provider=ModelProvider.OPENAI,
        thinking_enabled=True,
    )
    assert decision.mode == ReplayMode.RESPONSE_ID
    assert decision.use_previous_response_id is True
    assert decision.require_assistant_response_id is True
    assert decision.allow_recovery is True


def test_auto_mode_falls_back_to_manual_when_response_id_not_supported() -> None:
    decision = decide_replay_mode(
        configured_mode="auto",
        provider=ModelProvider.OLLAMA,
        thinking_enabled=False,
    )
    assert decision.mode == ReplayMode.MANUAL
    assert decision.use_previous_response_id is False
    assert decision.allow_recovery is False


def test_response_id_mode_is_strict() -> None:
    decision = decide_replay_mode(
        configured_mode="response_id",
        provider=ModelProvider.OPENAI,
        thinking_enabled=True,
    )
    assert decision.mode == ReplayMode.RESPONSE_ID
    assert decision.use_previous_response_id is True
    assert decision.allow_recovery is False

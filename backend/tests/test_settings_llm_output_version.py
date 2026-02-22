from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


@pytest.mark.parametrize("value", ["v0", "v1", "responses/v1"])
def test_settings_accept_supported_llm_output_versions(value: str) -> None:
    settings = Settings(LLM_OUTPUT_VERSION=value)
    assert settings.llm_output_version == value


def test_settings_reject_unknown_llm_output_version() -> None:
    with pytest.raises(ValidationError):
        Settings(LLM_OUTPUT_VERSION="unsupported")


@pytest.mark.parametrize("value", ["auto", "response_id", "manual"])
def test_settings_accept_supported_general_chat_replay_modes(value: str) -> None:
    settings = Settings(GENERAL_CHAT_REPLAY_MODE=value)
    assert settings.general_chat_replay_mode == value


def test_settings_reject_unknown_general_chat_replay_mode() -> None:
    with pytest.raises(ValidationError):
        Settings(GENERAL_CHAT_REPLAY_MODE="unsupported")

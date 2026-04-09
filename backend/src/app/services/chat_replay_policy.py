from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.models.model_config import ModelProvider


class ReplayMode(str, Enum):
    AUTO = "auto"
    RESPONSE_ID = "response_id"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class ReplayDecision:
    mode: ReplayMode
    use_previous_response_id: bool
    require_assistant_response_id: bool
    allow_recovery: bool


def decide_replay_mode(
    *,
    configured_mode: str,
    provider: ModelProvider,
    thinking_enabled: bool,
) -> ReplayDecision:
    mode = ReplayMode(configured_mode)
    supports_response_id_replay = provider == ModelProvider.OPENAI and bool(
        thinking_enabled
    )

    if mode == ReplayMode.MANUAL:
        return ReplayDecision(
            mode=mode,
            use_previous_response_id=False,
            require_assistant_response_id=False,
            allow_recovery=False,
        )

    if mode == ReplayMode.RESPONSE_ID:
        return ReplayDecision(
            mode=mode,
            use_previous_response_id=supports_response_id_replay,
            require_assistant_response_id=supports_response_id_replay,
            allow_recovery=False,
        )

    if supports_response_id_replay:
        return ReplayDecision(
            mode=ReplayMode.RESPONSE_ID,
            use_previous_response_id=True,
            require_assistant_response_id=True,
            allow_recovery=True,
        )
    return ReplayDecision(
        mode=ReplayMode.MANUAL,
        use_previous_response_id=False,
        require_assistant_response_id=False,
        allow_recovery=False,
    )

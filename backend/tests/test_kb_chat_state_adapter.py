from __future__ import annotations

from app.agents.kb_chat_contracts import STATE_SCHEMA_V3
from app.agents.kb_chat_state_adapter import normalize_checkpoint_state


def test_normalize_checkpoint_state_upgrades_legacy_shape() -> None:
    normalized = normalize_checkpoint_state(
        {
            "messages": [],
            "query_bundle": {"items": []},
            "loop_counts": {"total_rounds": 2},
        }
    )

    assert normalized["schema_version"] == STATE_SCHEMA_V3
    assert normalized["loop_counts"]["total_rounds"] == 2
    assert normalized["loop_counts"]["retrieval_retries"] == 0
    assert normalized["loop_counts"]["generation_retries"] == 0
    assert isinstance(normalized["query_bundle"], dict)
    assert isinstance(normalized["stage_summaries"], dict)
    assert isinstance(normalized["metrics"], dict)


def test_normalize_checkpoint_state_handles_invalid_payload() -> None:
    normalized = normalize_checkpoint_state(None)
    assert normalized == {}

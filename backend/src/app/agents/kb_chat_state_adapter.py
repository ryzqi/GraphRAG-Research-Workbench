"""State adapter layer for KB Chat checkpoint compatibility."""

from __future__ import annotations

from typing import Any, Mapping

from app.agents.kb_chat_contracts import (
    STATE_SCHEMA_V3,
    detect_state_schema_version,
)


def normalize_checkpoint_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize legacy checkpoint state into a v3-compatible shape."""

    if not isinstance(state, Mapping):
        return {}

    normalized = dict(state)
    schema_version = detect_state_schema_version(state)

    loop_counts = normalized.get("loop_counts")
    if not isinstance(loop_counts, dict):
        loop_counts = {}
    normalized["loop_counts"] = {
        "total_rounds": int(loop_counts.get("total_rounds") or 0),
        "retrieval_retries": int(loop_counts.get("retrieval_retries") or 0),
        "generation_retries": int(loop_counts.get("generation_retries") or 0),
    }

    stage_summaries = normalized.get("stage_summaries")
    normalized["stage_summaries"] = stage_summaries if isinstance(stage_summaries, dict) else {}

    metrics = normalized.get("metrics")
    normalized["metrics"] = metrics if isinstance(metrics, dict) else {}

    messages = normalized.get("messages")
    normalized["messages"] = messages if isinstance(messages, list) else []

    pending_tool_calls = normalized.get("pending_tool_calls")
    normalized["pending_tool_calls"] = (
        pending_tool_calls if isinstance(pending_tool_calls, list) else []
    )

    if schema_version in {"kb_chat_state_v1", "kb_chat_state_v2"}:
        rewrite_plan = normalized.get("rewrite_plan")
        normalized["rewrite_plan"] = rewrite_plan if isinstance(rewrite_plan, dict) else {}
        decomposition_plan = normalized.get("decomposition_plan")
        normalized["decomposition_plan"] = (
            decomposition_plan if isinstance(decomposition_plan, dict) else {}
        )
        query_bundle = normalized.get("query_bundle")
        normalized["query_bundle"] = query_bundle if isinstance(query_bundle, dict) else {}

    normalized["schema_version"] = STATE_SCHEMA_V3
    return normalized

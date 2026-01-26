"""JSON-safe helpers for KB chat graph state."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.settings import Settings

logger = logging.getLogger(__name__)


def ensure_json_safe(value: Any, *, settings: Settings, label: str) -> Any:
    """Ensure value is JSON-serializable; raise or downgrade based on settings."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError) as exc:
        # Always fail-fast outside prod to surface checkpoint errors early.
        if settings.app_env != "prod":
            raise ValueError(f"KB chat state is not JSON-safe: {label}") from exc

        policy = (
            getattr(settings, "kb_chat_json_safe_policy", "fail_fast") or "fail_fast"
        ).lower()
        policy = policy.replace("-", "_")
        if policy == "stringify":
            logger.warning(
                "KB chat state downgraded to JSON-safe", extra={"label": label}
            )
            try:
                return json.loads(json.dumps(value, default=str))
            except Exception:
                return str(value)

        raise ValueError(f"KB chat state is not JSON-safe: {label}") from exc

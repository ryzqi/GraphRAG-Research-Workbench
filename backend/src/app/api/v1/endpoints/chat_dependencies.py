from __future__ import annotations

from datetime import datetime, timezone


def stream_heartbeat_payload() -> dict[str, str]:
    return {
        "type": "heartbeat",
        "ts": datetime.now(timezone.utc).isoformat(),
    }

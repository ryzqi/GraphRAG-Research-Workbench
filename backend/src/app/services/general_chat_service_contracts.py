from __future__ import annotations

from typing import Any

SUMMARY_META_FLAG = "summary"
DEDUP_ATTACH_TIMEOUT_SECONDS = 5.0
DEDUP_RUN_WAIT_TIMEOUT_SECONDS = 25.0
DEDUP_POLL_INTERVAL_SECONDS = 0.5
DEDUP_TABLE_NAME = "chat_request_dedup"
_EXTERNAL_EVIDENCE_META_KEY = "_external_evidence_meta"


def _as_str_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}

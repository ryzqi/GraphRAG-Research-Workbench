from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any

from app.schemas.ingestion_batches import ManifestSourceType

MAX_MANIFEST_ENTRIES = 100
MAX_TEXT_LENGTH = 200_000
MAX_URL_ENTRIES = 50
MAX_FILE_ENTRIES = 50
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
ALLOWED_FILE_EXTENSIONS = {".pdf", ".md", ".txt", ".docx"}
AUTO_RETRY_DELAYS = (30, 120)
MAX_DOC_ATTEMPTS = 5
DOC_CANCELED_ERROR_CODE = "DOC_CANCELED"
INGESTION_DOC_TASK_NAME = "app.worker.tasks.ingestion_batches.run_ingestion_batch_doc"
_DEFAULT_URL_TIMEOUT_SECONDS = 25
_DEFAULT_URL_REDIRECTS = 3
_FALLBACK_BLOCKED_CIDRS_V4 = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
)
_FALLBACK_BLOCKED_CIDRS_V6 = (
    "::/128",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
)
_FALLBACK_METADATA_BLOCKED_IPS = ("169.254.169.254",)


@dataclass(frozen=True, slots=True)
class _BlockedCidrRule:
    network: ipaddress.IPv4Network | ipaddress.IPv6Network
    reason: str


@dataclass(slots=True)
class _PreparedEntry:
    entry_id: str
    source_type: ManifestSourceType
    title: str | None
    payload: dict[str, Any]
    fingerprint: str

from __future__ import annotations

from dataclasses import dataclass


MAX_UPLOAD_FILE_SIZE_BYTES = 50 * 1024 * 1024
ALLOWED_UPLOAD_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)
UPLOAD_MIME_TYPE_ALIASES = {
    "text/x-markdown": "text/markdown",
    "application/x-pdf": "application/pdf",
}
GENERIC_UPLOAD_MIME_TYPES = frozenset(
    {
        "application/octet-stream",
        "binary/octet-stream",
    }
)
ALLOWED_UPLOAD_EXTENSIONS = frozenset({".pdf", ".txt", ".md", ".docx"})


def normalize_upload_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None

    normalized = content_type.split(";", 1)[0].strip().lower()
    if not normalized:
        return None

    return UPLOAD_MIME_TYPE_ALIASES.get(normalized, normalized)


@dataclass(frozen=True, slots=True)
class UploadPolicySnapshot:
    max_file_size_bytes: int
    allowed_extensions: list[str]
    allowed_mime_types: list[str]
    mime_type_aliases: dict[str, str]
    generic_mime_types: list[str]


def build_upload_policy_snapshot() -> UploadPolicySnapshot:
    return UploadPolicySnapshot(
        max_file_size_bytes=MAX_UPLOAD_FILE_SIZE_BYTES,
        allowed_extensions=sorted(ALLOWED_UPLOAD_EXTENSIONS),
        allowed_mime_types=sorted(ALLOWED_UPLOAD_MIME_TYPES),
        mime_type_aliases=dict(sorted(UPLOAD_MIME_TYPE_ALIASES.items())),
        generic_mime_types=sorted(GENERIC_UPLOAD_MIME_TYPES),
    )

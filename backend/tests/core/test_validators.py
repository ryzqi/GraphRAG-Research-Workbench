from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.validators import validate_file_upload


def test_validate_file_upload_accepts_mime_with_charset_parameter() -> None:
    validate_file_upload(
        content=b"hello",
        filename="notes.txt",
        content_type="text/plain; charset=utf-8",
    )


def test_validate_file_upload_accepts_generic_octet_stream() -> None:
    validate_file_upload(
        content=b"markdown",
        filename="guide.md",
        content_type="application/octet-stream",
    )


def test_validate_file_upload_accepts_mime_alias() -> None:
    validate_file_upload(
        content=b"# title",
        filename="guide.md",
        content_type="text/x-markdown",
    )


def test_validate_file_upload_rejects_unsupported_mime_type() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_file_upload(
            content=b"fake",
            filename="guide.md",
            content_type="image/png",
        )

    assert exc_info.value.status_code == 415
    assert exc_info.value.detail["code"] == "INVALID_MIME_TYPE"

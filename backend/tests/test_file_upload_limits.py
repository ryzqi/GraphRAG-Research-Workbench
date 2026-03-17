from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.errors import AppError
from app.core.validators import validate_file_upload
from app.services.ingestion_batch_service import MAX_FILE_SIZE_BYTES
from app.services.kb_bootstrap_job_service import KBBootstrapJobService


class _SizedBlob:
    def __init__(self, size: int) -> None:
        self._size = size

    def __len__(self) -> int:
        return self._size


def test_validate_file_upload_rejects_file_larger_than_ingestion_limit() -> None:
    oversize = _SizedBlob(MAX_FILE_SIZE_BYTES + 1)

    with pytest.raises(HTTPException) as exc_info:
        validate_file_upload(oversize, "oversize.pdf", "application/pdf")

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail["code"] == "FILE_TOO_LARGE"
    assert "50MB" in exc_info.value.detail["message"]


def test_bootstrap_file_entry_rejects_file_larger_than_ingestion_limit() -> None:
    service = KBBootstrapJobService.__new__(KBBootstrapJobService)
    kb = SimpleNamespace(index_config={})

    with pytest.raises(AppError) as exc_info:
        service._validate_file_entry(
            kb=kb,
            extension=".pdf",
            file_size=MAX_FILE_SIZE_BYTES + 1,
            content_type="application/pdf",
        )

    assert exc_info.value.status_code == 413
    assert exc_info.value.code == "FILE_TOO_LARGE"
    assert "50MB" in exc_info.value.message

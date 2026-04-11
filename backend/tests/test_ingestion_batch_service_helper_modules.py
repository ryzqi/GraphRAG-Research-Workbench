from __future__ import annotations

from types import SimpleNamespace

from app.services.ingestion_batch_service_status import (
    _is_doc_canceled,
    _is_doc_failed,
    _is_doc_succeeded,
)
from app.services.ingestion_batch_service_url_security import _canonicalize_url
from app.models.ingestion_batch import IngestionDocStatus


def test_canonicalize_url_normalizes_scheme_host_and_fragment() -> None:
    assert (
        _canonicalize_url(" HTTPS://Example.COM/path?q=1#frag ")
        == "https://example.com/path?q=1"
    )


def test_doc_status_helpers_distinguish_failed_canceled_and_succeeded() -> None:
    canceled = SimpleNamespace(status=IngestionDocStatus.COMPLETED, error_code="DOC_CANCELED")
    failed = SimpleNamespace(status=IngestionDocStatus.COMPLETED, error_code="PARSER_FAILED")
    succeeded = SimpleNamespace(status=IngestionDocStatus.COMPLETED, error_code=None)

    assert _is_doc_canceled(canceled) is True
    assert _is_doc_failed(canceled) is False
    assert _is_doc_failed(failed) is True
    assert _is_doc_succeeded(succeeded) is True
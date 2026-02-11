from __future__ import annotations

import pytest

from app.db.schema_guard import IngestionSchemaMismatchError, validate_ingestion_enum_values


def test_validate_ingestion_enum_values_accepts_two_state_labels() -> None:
    validate_ingestion_enum_values(
        {
            "ingestion_batch_status": ("processing", "completed"),
            "ingestion_doc_status": ("completed", "processing"),
        }
    )


def test_validate_ingestion_enum_values_rejects_legacy_batch_labels() -> None:
    with pytest.raises(IngestionSchemaMismatchError, match="ingestion_batch_status"):
        validate_ingestion_enum_values(
            {
                "ingestion_batch_status": ("queued", "running", "failed"),
                "ingestion_doc_status": ("processing", "completed"),
            }
        )


def test_validate_ingestion_enum_values_rejects_missing_doc_enum() -> None:
    with pytest.raises(IngestionSchemaMismatchError, match="ingestion_doc_status"):
        validate_ingestion_enum_values(
            {
                "ingestion_batch_status": ("processing", "completed"),
            }
        )

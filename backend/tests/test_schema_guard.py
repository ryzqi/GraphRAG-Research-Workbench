from __future__ import annotations

import pytest

from app.db.schema_guard import (
    IngestionSchemaMismatchError,
    validate_ingestion_enum_values,
)


def test_validate_ingestion_enum_values_reports_schema_not_ready_when_enum_missing() -> None:
    with pytest.raises(RuntimeError, match="数据库未初始化/未迁移|schema not ready|missing"):
        validate_ingestion_enum_values(
            {
                "ingestion_batch_status": (),
                "ingestion_doc_status": (),
            }
        )


def test_validate_ingestion_enum_values_still_reports_mismatch_for_unexpected_labels() -> None:
    with pytest.raises(IngestionSchemaMismatchError, match="enum mismatch"):
        validate_ingestion_enum_values(
            {
                "ingestion_batch_status": ("processing", "failed"),
                "ingestion_doc_status": ("processing", "completed"),
            }
        )

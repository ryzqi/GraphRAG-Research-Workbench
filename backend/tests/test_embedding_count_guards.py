from __future__ import annotations

import pytest

from app.worker.tasks.ingestion_batches import _ProcessingFailure, _raise_on_embedding_count_mismatch
from app.worker.tasks.index_rebuild import _raise_on_index_rebuild_embedding_count_mismatch


def test_ingestion_embedding_count_mismatch_raises_retryable_processing_failure() -> None:
    with pytest.raises(_ProcessingFailure) as exc_info:
        _raise_on_embedding_count_mismatch(
            expected_count=3,
            actual_count=2,
            doc_id="doc-1",
            material_id="material-1",
        )

    assert exc_info.value.code == "EMBEDDING_COUNT_MISMATCH"
    assert exc_info.value.retryable is True


def test_index_rebuild_embedding_count_mismatch_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="EMBEDDING_COUNT_MISMATCH"):
        _raise_on_index_rebuild_embedding_count_mismatch(
            expected_count=4,
            actual_count=3,
            job_id="job-1",
            material_id="material-1",
        )

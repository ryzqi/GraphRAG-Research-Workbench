from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.chunk_persistence_service import ChunkPersistenceService
from app.services.chunking import ChunkItem
from app.utils.token_counter import count_tokens


@pytest.mark.asyncio
async def test_replace_material_chunks_persists_structured_window_and_source_fields() -> None:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()

    service = ChunkPersistenceService(db=db)
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    chunk_item = ChunkItem(
        content="alpha beta gamma",
        locator={"kind": "pdf", "page_start": 3, "page_end": 4},
        metadata={
            "chunking_strategy": "query_dependent_multiscale",
            "window_id": 1,
            "window_size_tokens": 200,
            "window_overlap_tokens": 40,
            "token_start": 120,
            "token_end": 220,
        },
    )

    written_ids = await service.replace_material_chunks(
        kb_id=kb_id,
        material_id=material_id,
        chunk_items=[chunk_item],
        chunk_ids=[chunk_id],
        embedding_texts=["alpha beta gamma"],
        context_texts=["ctx"],
        context_statuses=["ok"],
        context_errors=[None],
        context_attempts=[1],
    )

    assert written_ids == [chunk_id]
    assert db.execute.await_count == 2
    assert db.flush.await_count == 1

    insert_call = db.execute.await_args_list[1]
    rows = insert_call.args[1]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]

    assert row["global_chunk_order"] == 0
    assert row["chunking_strategy"] == "query_dependent_multiscale"
    assert row["window_id"] == 1
    assert row["window_size_tokens"] == 200
    assert row["window_overlap_tokens"] == 40
    assert row["token_start"] == 120
    assert row["token_end"] == 220
    assert row["source_kind"] == "pdf"
    assert row["source_page_start"] == 3
    assert row["source_page_end"] == 4
    assert row["token_count"] == count_tokens("alpha beta gamma")

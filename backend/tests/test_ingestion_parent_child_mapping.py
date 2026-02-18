from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.worker.tasks.ingestion_batches import _build_parent_id_by_ref, _resolve_parent_chunk_id


def test_parent_child_mapping_uses_parent_ref_for_child_chunks() -> None:
    parent_chunk_id = uuid.uuid4()
    child_chunk_id = uuid.uuid4()

    chunk_items = [
        SimpleNamespace(chunk_role="parent", parent_ref=None),
        SimpleNamespace(chunk_role="child", parent_ref=0),
    ]
    chunk_ids = [parent_chunk_id, child_chunk_id]

    mapping = _build_parent_id_by_ref(chunk_items=chunk_items, chunk_ids=chunk_ids)
    resolved = _resolve_parent_chunk_id(chunk_item=chunk_items[1], parent_id_by_ref=mapping)

    assert mapping == {0: str(parent_chunk_id)}
    assert resolved == str(parent_chunk_id)

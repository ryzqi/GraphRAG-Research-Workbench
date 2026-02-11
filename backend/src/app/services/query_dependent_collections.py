from __future__ import annotations


def collection_name_for_window(
    base_collection: str,
    chunk_size: int,
    chunk_overlap: int,
) -> str:
    normalized_base = base_collection.strip()
    if not normalized_base:
        raise ValueError("base_collection must be non-empty")

    return f"{normalized_base}__qdc_s{chunk_size}_o{chunk_overlap}"

from __future__ import annotations


def collection_name_for_window(
    base_collection: str,
    chunk_size_tokens: int,
    chunk_overlap_tokens: int,
) -> str:
    normalized_base = base_collection.strip()
    if not normalized_base:
        raise ValueError("base_collection must be non-empty")

    return (
        f"{normalized_base}"
        f"__msqdc_t{chunk_size_tokens}_o{chunk_overlap_tokens}"
    )

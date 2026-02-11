from __future__ import annotations

import pytest

from app.services.query_dependent_collections import collection_name_for_window


def test_collection_name_for_window_builds_expected_suffix() -> None:
    assert (
        collection_name_for_window(
            "knowledge_chunks",
            chunk_size=512,
            chunk_overlap=64,
        )
        == "knowledge_chunks__qdc_s512_o64"
    )


def test_collection_name_for_window_accepts_positional_window_args() -> None:
    assert (
        collection_name_for_window("knowledge_chunks", 512, 64)
        == "knowledge_chunks__qdc_s512_o64"
    )


def test_collection_name_for_window_is_deterministic() -> None:
    first = collection_name_for_window(
        "kb_main",
        chunk_size=128,
        chunk_overlap=32,
    )
    second = collection_name_for_window(
        "kb_main",
        chunk_size=128,
        chunk_overlap=32,
    )

    assert first == second


@pytest.mark.parametrize("base_collection", ["", "   ", "\t\n"])
def test_collection_name_for_window_rejects_empty_base(base_collection: str) -> None:
    with pytest.raises(ValueError):
        collection_name_for_window(
            base_collection,
            chunk_size=256,
            chunk_overlap=16,
        )

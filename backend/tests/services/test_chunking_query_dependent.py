from __future__ import annotations

import pytest

from app.schemas.knowledge_bases import IndexConfig
from app.services.chunking import ChunkingEngine
from app.services.parsing.types import ParsedChunk, ParsedDocument


class _FailingEmbedding:
    async def embed(self, *, texts: list[str]) -> list[list[float]]:
        raise RuntimeError(f"boom: {len(texts)}")


@pytest.mark.asyncio
async def test_query_dependent_chunking_emits_chunks_for_each_window() -> None:
    engine = ChunkingEngine()
    document = ParsedDocument(text="a" * 300, metadata={"source": "unit"})
    index_config = IndexConfig.model_validate(
        {
            "chunking": {
                "general_strategy": "query_dependent_chunking",
                "query_dependent_chunking": {
                    "windows": [
                        {"chunk_size": 128, "chunk_overlap": 0},
                        {"chunk_size": 160, "chunk_overlap": 32},
                    ]
                },
            }
        }
    )

    chunks = await engine.split(document, index_config)

    assert [len(item.content) for item in chunks] == [128, 128, 44, 160, 160, 44]
    assert {item.metadata["window_index"] for item in chunks} == {0, 1}
    assert [item.metadata for item in chunks] == [
        {
            "source": "unit",
            "chunking_strategy": "query_dependent_chunking",
            "window_index": 0,
            "window_size": 128,
            "window_overlap": 0,
            "index": 0,
        },
        {
            "source": "unit",
            "chunking_strategy": "query_dependent_chunking",
            "window_index": 0,
            "window_size": 128,
            "window_overlap": 0,
            "index": 1,
        },
        {
            "source": "unit",
            "chunking_strategy": "query_dependent_chunking",
            "window_index": 0,
            "window_size": 128,
            "window_overlap": 0,
            "index": 2,
        },
        {
            "source": "unit",
            "chunking_strategy": "query_dependent_chunking",
            "window_index": 1,
            "window_size": 160,
            "window_overlap": 32,
            "index": 0,
        },
        {
            "source": "unit",
            "chunking_strategy": "query_dependent_chunking",
            "window_index": 1,
            "window_size": 160,
            "window_overlap": 32,
            "index": 1,
        },
        {
            "source": "unit",
            "chunking_strategy": "query_dependent_chunking",
            "window_index": 1,
            "window_size": 160,
            "window_overlap": 32,
            "index": 2,
        },
    ]


@pytest.mark.asyncio
async def test_default_non_markdown_path_uses_query_dependent_windows() -> None:
    engine = ChunkingEngine()

    chunks = await engine.split(ParsedDocument(text="hello world"), IndexConfig())

    assert [item.content for item in chunks] == ["hello world"]
    assert chunks[0].metadata == {
        "chunking_strategy": "query_dependent_chunking",
        "window_index": 0,
        "window_size": 512,
        "window_overlap": 64,
        "index": 0,
    }


@pytest.mark.asyncio
async def test_semantic_fallback_uses_first_query_dependent_window() -> None:
    engine = ChunkingEngine(embedding=_FailingEmbedding())  # type: ignore[arg-type]
    index_config = IndexConfig.model_validate(
        {
            "chunking": {
                "general_strategy": "max_min_semantic",
                "query_dependent_chunking": {
                    "windows": [
                        {"chunk_size": 128, "chunk_overlap": 32},
                        {"chunk_size": 256, "chunk_overlap": 64},
                    ]
                },
            }
        }
    )

    chunks = await engine.split(ParsedDocument(text="a" * 300), index_config)

    assert [len(item.content) for item in chunks] == [128, 128, 108]
    assert [item.metadata for item in chunks] == [
        {"chunking_strategy": "max_min_semantic", "index": 0},
        {"chunking_strategy": "max_min_semantic", "index": 1},
        {"chunking_strategy": "max_min_semantic", "index": 2},
    ]


@pytest.mark.asyncio
async def test_pdf_blocks_do_not_require_removed_sliding_window() -> None:
    engine = ChunkingEngine()
    document = ParsedDocument(
        text="",
        mime_type="application/pdf",
        chunks=[
            ParsedChunk(text="first", locator={"kind": "pdf", "page_start": 1, "page_end": 1}),
            ParsedChunk(text="second", locator={"kind": "pdf", "page_start": 1, "page_end": 1}),
        ],
    )
    index_config = IndexConfig.model_validate(
        {
            "chunking": {
                "query_dependent_chunking": {
                    "windows": [{"chunk_size": 512, "chunk_overlap": 0}]
                }
            }
        }
    )

    chunks = await engine.split(document, index_config)

    assert [item.content for item in chunks] == ["first\n\nsecond"]
    assert chunks[0].metadata == {
        "chunking_strategy": "query_dependent_chunking",
        "window_index": 0,
        "window_size": 512,
        "window_overlap": 0,
        "index": 0,
    }


@pytest.mark.asyncio
async def test_pdf_blocks_apply_each_window_across_full_document() -> None:
    engine = ChunkingEngine()
    document = ParsedDocument(
        text="",
        mime_type="application/pdf",
        chunks=[
            ParsedChunk(
                text="A" * 60,
                locator={
                    "kind": "pdf",
                    "page_start": 1,
                    "page_end": 1,
                    "blocks": [{"id": "p1_b1"}],
                },
                metadata={"mineru_block_type": "text"},
            ),
            ParsedChunk(
                text="B" * 60,
                locator={
                    "kind": "pdf",
                    "page_start": 2,
                    "page_end": 2,
                    "blocks": [{"id": "p2_b1"}],
                },
                metadata={"mineru_block_type": "text"},
            ),
            ParsedChunk(
                text="C" * 60,
                locator={
                    "kind": "pdf",
                    "page_start": 3,
                    "page_end": 3,
                    "blocks": [{"id": "p3_b1"}],
                },
                metadata={"mineru_block_type": "text"},
            ),
            ParsedChunk(
                text="D" * 60,
                locator={
                    "kind": "pdf",
                    "page_start": 4,
                    "page_end": 4,
                    "blocks": [{"id": "p4_b1"}],
                },
                metadata={"mineru_block_type": "text"},
            ),
        ],
    )
    index_config = IndexConfig.model_validate(
        {
            "chunking": {
                "query_dependent_chunking": {
                    "windows": [
                        {"chunk_size": 128, "chunk_overlap": 0},
                        {"chunk_size": 200, "chunk_overlap": 0},
                    ]
                }
            }
        }
    )

    chunks = await engine.split(document, index_config)

    window_zero = [item for item in chunks if item.metadata["window_index"] == 0]
    window_one = [item for item in chunks if item.metadata["window_index"] == 1]

    assert len(window_zero) == 2
    assert [len(item.locator["blocks"]) for item in window_zero] == [3, 1]
    assert len(window_one) == 1
    assert window_one[0].locator["page_start"] == 1
    assert window_one[0].locator["page_end"] == 4
    assert len(window_one[0].locator["blocks"]) == 4
    assert window_one[0].metadata == {
        "mineru_block_types": ["text", "text", "text", "text"],
        "chunking_strategy": "query_dependent_chunking",
        "window_index": 1,
        "window_size": 200,
        "window_overlap": 0,
        "index": 0,
    }


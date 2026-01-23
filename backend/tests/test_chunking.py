import pytest

from app.core.settings import Settings
from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig
from app.services.chunking import ChunkingEngine, TextChunker
from app.services.parsing.types import ParsedChunk, ParsedDocument


class DummyEmbedding:
    async def embed(self, *, texts: list[str]) -> list[list[float]]:
        vectors = []
        for idx, _ in enumerate(texts):
            vectors.append([1.0, 0.0] if idx % 2 == 0 else [0.0, 1.0])
        return vectors


@pytest.mark.asyncio
async def test_sliding_window_chunking() -> None:
    settings = Settings(
        ingestion_chunk_strategy="sliding_window",
        ingestion_chunk_size=4,
        ingestion_chunk_overlap=1,
    )
    chunker = TextChunker(settings=settings)
    chunks = await chunker.split("abcdefg")

    assert chunks == ["abcd", "defg"]


@pytest.mark.asyncio
async def test_semantic_chunking_splits_on_low_similarity() -> None:
    settings = Settings(
        ingestion_chunk_strategy="max_min_semantic",
        ingestion_semantic_min_tokens=1,
        ingestion_semantic_max_tokens=100,
        ingestion_semantic_similarity_threshold=0.9,
    )
    chunker = TextChunker(settings=settings, embedding=DummyEmbedding())
    chunks = await chunker.split("第一句。第二句。第三句。")

    assert len(chunks) == 3


@pytest.mark.asyncio
async def test_parent_child_chunking_outputs_parent_and_child() -> None:
    doc = ParsedDocument(text="abcdefghij12345", mime_type="text/plain")
    config = IndexConfig()
    config.chunking.general_strategy = ChunkingStrategy.PARENT_CHILD
    config.chunking.parent_child.parent.chunk_size = 10
    config.chunking.parent_child.parent.chunk_overlap = 0
    config.chunking.parent_child.child.chunk_size = 4
    config.chunking.parent_child.child.chunk_overlap = 0

    engine = ChunkingEngine(settings=Settings())
    chunks = await engine.split(doc, config)

    assert any(c.chunk_role == "parent" for c in chunks)
    assert any(c.chunk_role == "child" for c in chunks)
    assert any(c.chunk_role == "child" and c.parent_ref is not None for c in chunks)


@pytest.mark.asyncio
async def test_markdown_heading_chunking_uses_heading_metadata() -> None:
    pytest.importorskip("langchain_text_splitters")
    doc = ParsedDocument(text="# Title\n\nContent", mime_type="text/markdown")
    config = IndexConfig()
    engine = ChunkingEngine(settings=Settings())
    chunks = await engine.split(doc, config)

    assert chunks
    assert any(c.metadata and c.metadata.get("chunking_strategy") == "markdown_heading" for c in chunks)


@pytest.mark.asyncio
async def test_pdf_block_aggregation_merges_locator() -> None:
    blocks = [
        ParsedChunk(text="hello ", locator={"kind": "pdf", "page": 1}),
        ParsedChunk(text="world", locator={"kind": "pdf", "page": 1}),
    ]
    doc = ParsedDocument(text="", mime_type="application/pdf", chunks=blocks)
    config = IndexConfig()
    config.chunking.sliding_window.chunk_size = 50
    config.chunking.sliding_window.chunk_overlap = 0
    engine = ChunkingEngine(settings=Settings())
    chunks = await engine.split(doc, config)

    assert chunks
    assert chunks[0].locator
    assert chunks[0].locator.get("kind") == "pdf"


@pytest.mark.asyncio
async def test_pdf_parent_child_strategy_respected() -> None:
    blocks = [
        ParsedChunk(text="abcdef ", locator={"kind": "pdf", "page": 1}),
        ParsedChunk(text="ghijkl ", locator={"kind": "pdf", "page": 1}),
        ParsedChunk(text="mnopqr", locator={"kind": "pdf", "page": 1}),
    ]
    doc = ParsedDocument(text="", mime_type="application/pdf", chunks=blocks)
    config = IndexConfig()
    config.chunking.general_strategy = ChunkingStrategy.PARENT_CHILD
    config.chunking.parent_child.parent.chunk_size = 20
    config.chunking.parent_child.parent.chunk_overlap = 0
    config.chunking.parent_child.child.chunk_size = 6
    config.chunking.parent_child.child.chunk_overlap = 0

    engine = ChunkingEngine(settings=Settings())
    chunks = await engine.split(doc, config)

    assert any(c.chunk_role == "parent" for c in chunks)
    assert any(c.chunk_role == "child" for c in chunks)
    assert any(c.locator and c.locator.get("kind") == "pdf" for c in chunks)

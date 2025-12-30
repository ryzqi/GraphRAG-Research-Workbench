import pytest

from app.core.settings import Settings
from app.services.chunking import TextChunker


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

from __future__ import annotations

import asyncio
from typing import Any


async def embed_inputs_with_concurrency(
    *,
    embedding_client: Any,
    embedding_inputs: list[str],
    batch_size: int,
    fanout_concurrency: int,
) -> list[list[float]]:
    if not embedding_inputs:
        return []

    normalized_batch_size = max(int(batch_size), 1)
    semaphore = asyncio.Semaphore(max(int(fanout_concurrency), 1))
    batches = [
        embedding_inputs[start : start + normalized_batch_size]
        for start in range(0, len(embedding_inputs), normalized_batch_size)
    ]

    async def _embed_batch(batch: list[str]) -> list[list[float]]:
        async with semaphore:
            return await embedding_client.embed(texts=batch)

    embeddings_by_batch = await asyncio.gather(*[_embed_batch(batch) for batch in batches])
    return [embedding for batch in embeddings_by_batch for embedding in batch]

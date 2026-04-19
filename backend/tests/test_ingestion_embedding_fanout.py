from __future__ import annotations

import asyncio

import pytest

from app.worker.tasks.embedding_fanout import embed_inputs_with_concurrency


class _FakeEmbeddingClient:
    def __init__(self) -> None:
        self.active_calls = 0
        self.max_active_calls = 0
        self.seen_batches: list[list[str]] = []

    async def embed(self, *, texts: list[str]) -> list[list[float]]:
        self.seen_batches.append(list(texts))
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        await asyncio.sleep(0.05)
        self.active_calls -= 1
        return [[float(text)] for text in texts]


@pytest.mark.asyncio
async def test_embed_inputs_with_concurrency_fans_out_batches_and_preserves_order() -> None:
    client = _FakeEmbeddingClient()
    inputs = [str(index) for index in range(32 * 5)]

    embeddings = await embed_inputs_with_concurrency(
        embedding_client=client,
        embedding_inputs=inputs,
        batch_size=32,
        fanout_concurrency=4,
    )

    assert client.max_active_calls == 4
    assert client.seen_batches == [
        inputs[0:32],
        inputs[32:64],
        inputs[64:96],
        inputs[96:128],
        inputs[128:160],
    ]
    assert embeddings == [[float(text)] for text in inputs]


@pytest.mark.asyncio
async def test_embed_inputs_with_concurrency_propagates_batch_failures() -> None:
    class _FailingEmbeddingClient:
        async def embed(self, *, texts: list[str]) -> list[list[float]]:
            if texts == ["2", "3"]:
                raise RuntimeError("batch failed")
            await asyncio.sleep(0.01)
            return [[float(text)] for text in texts]

    with pytest.raises(RuntimeError, match="batch failed"):
        await embed_inputs_with_concurrency(
            embedding_client=_FailingEmbeddingClient(),
            embedding_inputs=["0", "1", "2", "3"],
            batch_size=2,
            fanout_concurrency=1,
        )

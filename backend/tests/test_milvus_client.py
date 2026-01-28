from __future__ import annotations

import pytest

from app.integrations import milvus_client as mc


def _set_weighted_ranker(monkeypatch):
    captured: dict[str, tuple] = {}

    def fake_ranker(*args, **kwargs):  # noqa: ANN001
        captured["args"] = args
        return {"args": args, "kwargs": kwargs}

    monkeypatch.setattr(mc, "WeightedRanker", fake_ranker)
    return captured


def test_weighted_ranker_uses_positional_args(monkeypatch):
    captured = _set_weighted_ranker(monkeypatch)
    reqs = [object(), object()]
    mc._build_weighted_ranker([0.7, 0.3], reqs)
    assert captured["args"] == (0.7, 0.3)


def test_weighted_ranker_mismatch_raises(monkeypatch):
    _set_weighted_ranker(monkeypatch)
    with pytest.raises(ValueError):
        mc._build_weighted_ranker([0.7], [object(), object()])


@pytest.mark.asyncio
async def test_milvus_client_aclose_closes_underlying(monkeypatch):
    class DummyAsyncMilvusClient:
        def __init__(self, uri: str) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(mc, "AsyncMilvusClient", DummyAsyncMilvusClient)

    client = mc.MilvusClient()
    await client.aclose()
    assert client._client.closed is True

from __future__ import annotations

from types import SimpleNamespace

from app.integrations.rerank_client import RerankClient


def _make_settings(**overrides: object) -> SimpleNamespace:
    defaults = {
        "retrieval_rerank_base_url": "https://rerank.example.com",
        "retrieval_rerank_api_key": "test-key",
        "retrieval_rerank_model": "rerank-v1",
        "retrieval_rerank_timeout_seconds": 5.0,
        "retrieval_rerank_max_documents_per_request": 2,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class _DummyResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeHttpClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
        timeout: float,
    ) -> _DummyResponse:
        self.calls.append(
            {
                "url": url,
                "json": dict(json),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        return _DummyResponse(self._responses[len(self.calls) - 1])


async def test_rerank_batches_documents_and_merges_global_scores() -> None:
    http_client = _FakeHttpClient(
        [
            {
                "results": [
                    {"index": 1, "relevance_score": 0.30},
                    {"index": 0, "relevance_score": 0.20},
                ]
            },
            {
                "results": [
                    {"index": 0, "relevance_score": 0.95},
                    {"index": 1, "relevance_score": 0.10},
                ]
            },
            {"results": [{"index": 0, "relevance_score": 0.99}]},
        ]
    )
    client = RerankClient(
        settings=_make_settings(retrieval_rerank_max_documents_per_request=2),
        http_client=http_client,
    )

    results = await client.rerank(
        query="哪个文档最相关？",
        documents=["doc-0", "doc-1", "doc-2", "doc-3", "doc-4"],
        top_n=2,
    )

    assert [item.index for item in results] == [4, 2]
    assert [item.score for item in results] == [0.99, 0.95]
    assert [call["json"]["documents"] for call in http_client.calls] == [
        ["doc-0", "doc-1"],
        ["doc-2", "doc-3"],
        ["doc-4"],
    ]
    assert [call["json"]["top_n"] for call in http_client.calls] == [2, 2, 1]

"""Rerank 客户端（OpenAI 兼容 rerank API）。"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

import httpx

from app.core.settings import Settings, get_settings


@dataclass(slots=True)
class RerankResult:
    index: int
    score: float


class RerankClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._http_client = http_client
        self._base_url = self._settings.retrieval_rerank_base_url.rstrip("/")
        self._api_key = self._settings.retrieval_rerank_api_key
        self._model = self._settings.retrieval_rerank_model

    async def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int | None = None,
        timeout_seconds: float | None = None,
    ) -> list[RerankResult]:
        if not documents:
            return []

        max_documents = self._settings.retrieval_rerank_max_documents_per_request
        top_n = min(top_n or len(documents), len(documents))
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        timeout = timeout_seconds or self._settings.retrieval_rerank_timeout_seconds
        url = f"{self._base_url}/rerank"
        if self._http_client is None:
            raise RuntimeError(
                "RerankClient 必须注入共享 http_client；请通过 AppResources.http_client "
                "或 TaskResources.http_client 传入"
            )

        if max_documents is None or len(documents) <= max_documents:
            batches = [documents]
        else:
            batches = [
                documents[i : i + max_documents]
                for i in range(0, len(documents), max_documents)
            ]

        async def _call_batch(
            client: httpx.AsyncClient,
            *,
            batch_documents: list[str],
            batch_top_n: int,
        ) -> list[RerankResult]:
            payload = {
                "model": self._model,
                "query": query,
                "documents": batch_documents,
                "top_n": batch_top_n,
                "return_documents": False,
            }
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    resp = await client.post(
                        url, json=payload, headers=headers, timeout=timeout
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    results: list[RerankResult] = []
                    for item in data.get("results", []):
                        index = item.get("index")
                        score = item.get("relevance_score")
                        if index is None or score is None:
                            continue
                        results.append(
                            RerankResult(index=int(index), score=float(score))
                        )
                    return results
                except Exception as exc:  # pragma: no cover
                    last_exc = exc
                    if attempt < 1:
                        delay = 0.2 * (2**attempt)
                        delay = delay * (1 + random.random() * 0.2)
                        await asyncio.sleep(delay)
            raise RuntimeError("Rerank 调用失败") from last_exc

        batch_results = await asyncio.gather(
            *(
                _call_batch(
                    self._http_client,
                    batch_documents=batch,
                    batch_top_n=min(top_n, len(batch)),
                )
                for batch in batches
            )
        )

        merged_results: list[RerankResult] = []
        batch_offset = 0
        for batch_documents, results in zip(batches, batch_results, strict=False):
            for item in results:
                merged_results.append(
                    RerankResult(index=item.index + batch_offset, score=item.score)
                )
            batch_offset += len(batch_documents)

        merged_results.sort(key=lambda item: item.score, reverse=True)
        if top_n < len(merged_results):
            return merged_results[:top_n]
        return merged_results

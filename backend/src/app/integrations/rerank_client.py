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
        if max_documents is not None and len(documents) > max_documents:
            documents = documents[:max_documents]

        top_n = min(top_n or len(documents), len(documents))
        payload = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": False,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        timeout = timeout_seconds or self._settings.retrieval_rerank_timeout_seconds
        url = f"{self._base_url}/rerank"

        async def _call(client: httpx.AsyncClient) -> dict:
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    resp = await client.post(
                        url, json=payload, headers=headers, timeout=timeout
                    )
                    resp.raise_for_status()
                    return resp.json()
                except Exception as exc:  # pragma: no cover
                    last_exc = exc
                    if attempt < 1:
                        delay = 0.2 * (2**attempt)
                        delay = delay * (1 + random.random() * 0.2)
                        await asyncio.sleep(delay)
            raise RuntimeError("Rerank 调用失败") from last_exc

        if self._http_client is not None:
            data = await _call(self._http_client)
        else:
            async with httpx.AsyncClient(timeout=timeout) as client:
                data = await _call(client)

        results: list[RerankResult] = []
        for item in data.get("results", []):
            index = item.get("index")
            score = item.get("relevance_score")
            if index is None or score is None:
                continue
            results.append(RerankResult(index=int(index), score=float(score)))

        return results

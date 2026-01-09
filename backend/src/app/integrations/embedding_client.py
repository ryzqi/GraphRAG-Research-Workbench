from __future__ import annotations

import asyncio
import random

import httpx

from app.core.settings import get_settings


class EmbeddingClient:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self._http_client = http_client
        self._base_url = settings.embedding_base_url.rstrip("/")
        self._api_key = settings.embedding_api_key
        self._model = settings.embedding_model

    async def embed(self, *, texts: list[str], timeout_seconds: float = 30.0) -> list[list[float]]:
        url = f"{self._base_url}/embeddings"
        payload = {"model": self._model, "input": texts}
        headers = {"Authorization": f"Bearer {self._api_key}"}

        async def _call(client: httpx.AsyncClient) -> list[list[float]]:
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    resp = await client.post(
                        url, json=payload, headers=headers, timeout=timeout_seconds
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return [item["embedding"] for item in data["data"]]
                except Exception as exc:  # pragma: no cover
                    last_exc = exc
                    if attempt < 1:
                        delay = 0.2 * (2**attempt)
                        delay = delay * (1 + random.random() * 0.2)
                        await asyncio.sleep(delay)
            raise RuntimeError("Embedding 调用失败") from last_exc

        if self._http_client is not None:
            return await _call(self._http_client)

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            return await _call(client)

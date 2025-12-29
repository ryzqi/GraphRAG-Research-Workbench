from __future__ import annotations

import httpx

from app.core.settings import get_settings


class EmbeddingClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.embedding_base_url.rstrip("/")
        self._api_key = settings.embedding_api_key
        self._model = settings.embedding_model

    async def embed(self, *, texts: list[str], timeout_seconds: float = 30.0) -> list[list[float]]:
        url = f"{self._base_url}/embeddings"
        payload = {"model": self._model, "input": texts}
        headers = {"Authorization": f"Bearer {self._api_key}"}

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]

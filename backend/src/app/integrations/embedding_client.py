from __future__ import annotations

import asyncio
import random

import httpx

from app.core.settings import get_settings


class EmbeddingDimensionMismatchError(RuntimeError):
    """Raised when the provider returns a vector size that does not match config."""


class EmbeddingClient:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._http_client = http_client
        self._base_url = settings.embedding_base_url.rstrip("/")
        self._api_key = settings.embedding_api_key
        self._model = settings.embedding_model
        self._expected_dim = settings.embedding_dim

    def _validate_embedding_dimensions(self, embeddings: list[list[float]]) -> None:
        expected_dim = self._expected_dim
        if expected_dim is None:
            return
        for embedding in embeddings:
            actual_dim = len(embedding)
            if actual_dim != expected_dim:
                raise EmbeddingDimensionMismatchError(
                    "Embedding 维度与配置不一致: "
                    f"model={self._model}, expected={expected_dim}, actual={actual_dim}. "
                    "请检查 EMBEDDING_DIM、EMBEDDING_MODEL 与向量库 schema 是否一致。"
                )

    async def embed(
        self, *, texts: list[str], timeout_seconds: float | None = None
    ) -> list[list[float]]:
        url = f"{self._base_url}/embeddings"
        payload: dict[str, object] = {"model": self._model, "input": texts}
        if self._expected_dim is not None:
            payload["dimensions"] = self._expected_dim
        headers = {"Authorization": f"Bearer {self._api_key}"}
        timeout = (
            self._settings.embedding_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )

        async def _call(client: httpx.AsyncClient) -> list[list[float]]:
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    resp = await client.post(
                        url, json=payload, headers=headers, timeout=timeout
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    embeddings = [item["embedding"] for item in data["data"]]
                    self._validate_embedding_dimensions(embeddings)
                    return embeddings
                except EmbeddingDimensionMismatchError:
                    raise
                except Exception as exc:  # pragma: no cover
                    last_exc = exc
                    if attempt < 1:
                        delay = 0.2 * (2**attempt)
                        delay = delay * (1 + random.random() * 0.2)
                        await asyncio.sleep(delay)
            raise RuntimeError("Embedding 调用失败") from last_exc

        if self._http_client is not None:
            return await _call(self._http_client)

        async with httpx.AsyncClient(timeout=timeout) as client:
            return await _call(client)

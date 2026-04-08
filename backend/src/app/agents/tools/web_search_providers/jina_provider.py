"""Jina Reader provider 适配。"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.settings import Settings
from app.integrations.http_client import create_http_client

from .base import build_provider_error


def _extract_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return status_code if isinstance(status_code, int) else None


class _JinaHttpMixin:
    def __init__(
        self,
        *,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client

    async def _request_json(
        self,
        url: str,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if self._http_client is None:
            client = create_http_client(self._settings)
            try:
                response = await client.get(url, headers=headers, timeout=None)
                response.raise_for_status()
                return response.json()
            finally:
                await client.aclose()
        response = await self._http_client.get(url, headers=headers, timeout=None)
        response.raise_for_status()
        return response.json()


class JinaReadProvider(_JinaHttpMixin):
    provider_name = "jina_reader"

    async def read(
        self,
        *,
        url: str,
    ) -> dict[str, Any]:
        request_url = f"{self._settings.jina_read_base_url.rstrip('/')}/{url}"
        try:
            payload = await self._request_json(request_url)
        except Exception as exc:
            return {
                "url": url,
                "title": "",
                "content": "",
                "error": build_provider_error(
                    code="JINA_READ_UPSTREAM_ERROR",
                    message="Jina 页面读取暂时不可用，请稍后重试",
                    retryable=isinstance(
                        exc, (httpx.TimeoutException, httpx.HTTPStatusError)
                    ),
                    detail=str(exc),
                    status_code=_extract_status_code(exc),
                ),
            }

        if isinstance(payload, dict):
            body = (
                payload.get("data")
                if isinstance(payload.get("data"), dict)
                else payload
            )
            return {
                "url": str(body.get("url") or url),
                "title": str(body.get("title") or ""),
                "content": str(body.get("content") or body.get("text") or ""),
                "description": body.get("description"),
                "error": None,
            }
        return {
            "url": url,
            "title": "",
            "content": str(payload or ""),
            "error": None,
        }

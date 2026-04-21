"""Celery worker 进程级 Deep Research runtime 缓存。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import httpx

from app.core.settings import Settings
from app.integrations.http_client import (
    build_http_timeout,
    close_http_client,
    create_http_client,
)
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.integrations.redis_client import (
    RedisClient,
    close_redis_client,
    create_redis_client,
)
from app.services.deep_research_runtime import (
    DeepResearchRuntimeRunner,
    build_deep_research_runtime_runner,
)


def _settings_fingerprint(settings: Settings) -> str:
    payload = settings.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


class _LoopLocalHttpClientProxy:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._timeout = build_http_timeout(settings)
        self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def timeout(self) -> httpx.Timeout:
        return self._timeout

    async def _get_client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if self._client is not None and self._loop is loop:
            return self._client

        stale_client = self._client
        self._client = create_http_client(self._settings)
        self._loop = loop
        if stale_client is not None:
            await close_http_client(stale_client)
        return self._client

    async def request(self, *args: Any, **kwargs: Any) -> httpx.Response:
        client = await self._get_client()
        return await client.request(*args, **kwargs)

    async def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        client = await self._get_client()
        return await client.get(*args, **kwargs)

    async def aclose(self) -> None:
        stale_client = self._client
        self._client = None
        self._loop = None
        if stale_client is not None:
            await close_http_client(stale_client)


class _LoopLocalRedisClientProxy:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: RedisClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def _get_client(self) -> RedisClient:
        loop = asyncio.get_running_loop()
        if self._client is not None and self._loop is loop:
            return self._client

        stale_client = self._client
        self._client = create_redis_client(self._settings)
        self._loop = loop
        if stale_client is not None:
            await close_redis_client(stale_client)
        return self._client

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        client = await self._get_client()
        return await client.get(*args, **kwargs)

    async def set(self, *args: Any, **kwargs: Any) -> Any:
        client = await self._get_client()
        return await client.set(*args, **kwargs)

    async def aclose(self) -> None:
        stale_client = self._client
        self._client = None
        self._loop = None
        if stale_client is not None:
            await close_redis_client(stale_client)


class DeepResearchRuntimeCache:
    _runner: DeepResearchRuntimeRunner | None = None
    _key: tuple[str, int] | None = None
    _settings_fingerprint: str | None = None
    _http_client: _LoopLocalHttpClientProxy | None = None
    _redis: _LoopLocalRedisClientProxy | None = None
    _lock: asyncio.Lock | None = None
    _lock_loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if cls._lock is None or cls._lock_loop is not loop:
            cls._lock = asyncio.Lock()
            cls._lock_loop = loop
        return cls._lock

    @classmethod
    async def _close_shared_clients(cls) -> None:
        if cls._http_client is not None:
            await cls._http_client.aclose()
        if cls._redis is not None:
            await cls._redis.aclose()
        cls._http_client = None
        cls._redis = None
        cls._settings_fingerprint = None

    @classmethod
    async def _ensure_shared_clients(
        cls,
        *,
        settings: Settings,
        settings_fingerprint: str,
    ) -> None:
        if (
            cls._settings_fingerprint == settings_fingerprint
            and cls._http_client is not None
            and cls._redis is not None
        ):
            return
        await cls._close_shared_clients()
        cls._http_client = _LoopLocalHttpClientProxy(settings)
        cls._redis = _LoopLocalRedisClientProxy(settings)
        cls._settings_fingerprint = settings_fingerprint

    @classmethod
    async def get(
        cls,
        *,
        settings: Settings,
    ) -> DeepResearchRuntimeRunner:
        snapshot = ModelRuntimeConfigManager.get_snapshot(settings=settings)
        version = int(getattr(snapshot, "version", 0))
        settings_fingerprint = _settings_fingerprint(settings)
        key = (settings_fingerprint, version)

        if cls._runner is not None and cls._key == key:
            return cls._runner

        lock = cls._get_lock()
        async with lock:
            if cls._runner is not None and cls._key == key:
                return cls._runner
            await cls._ensure_shared_clients(
                settings=settings,
                settings_fingerprint=settings_fingerprint,
            )
            runner = await build_deep_research_runtime_runner(
                settings=settings,
                http_client=cls._http_client,
                redis=cls._redis,
            )
            cls._runner = runner
            cls._key = key
            return runner

    @classmethod
    async def shutdown(cls) -> None:
        await cls._close_shared_clients()
        cls._runner = None
        cls._key = None
        cls._lock = None
        cls._lock_loop = None

    @classmethod
    def reset(cls) -> None:
        cls._runner = None
        cls._key = None
        cls._settings_fingerprint = None
        cls._http_client = None
        cls._redis = None
        cls._lock = None
        cls._lock_loop = None


async def get_cached_runner(
    *,
    settings: Settings,
) -> DeepResearchRuntimeRunner:
    return await DeepResearchRuntimeCache.get(settings=settings)

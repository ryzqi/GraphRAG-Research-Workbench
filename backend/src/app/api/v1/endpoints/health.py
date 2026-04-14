from __future__ import annotations

import asyncio
import inspect
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.dependencies.app_resources import AppResourcesDep
from app.core.checkpoint import CheckpointManager
from app.core.errors import build_error_response
from app.core.logging import get_request_id
from app.core.memory_store import StoreManager
from app.integrations.milvus_client import MilvusClient
from app.integrations.object_storage import ObjectStorage
from app.integrations.redis_client import RedisClient

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _timed(name: str, coro, timeout_seconds: float) -> dict[str, object]:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout=timeout_seconds)
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "ok": True,
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "error": None,
    }


async def _check_postgres(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis(redis: RedisClient) -> None:
    ping_result = redis.ping()
    if inspect.isawaitable(ping_result):
        await ping_result


async def _check_milvus(milvus: MilvusClient) -> None:
    await milvus.ready_check()


async def _check_minio() -> None:
    storage = ObjectStorage()

    def _check() -> None:
        storage._client.bucket_exists(storage._settings.minio_bucket_uploads)

    await asyncio.to_thread(_check)


def _status_dependency(payload: dict[str, object]) -> dict[str, object]:
    status = str(payload.get("status") or "unknown")
    ok = status in {"ready", "disabled"}
    result = dict(payload)
    result["ok"] = ok
    result["latency_ms"] = 0
    result["error"] = None if ok else payload.get("reason")
    return result


@router.get("/ready")
async def ready(resources: AppResourcesDep) -> JSONResponse:
    """Readiness：短超时探测关键依赖，可降级返回。"""
    engine = resources.engine
    redis = resources.redis
    milvus = resources.milvus_client
    tasks = {
        "postgres": asyncio.create_task(
            _timed("postgres", _check_postgres(engine), 1.0)
        ),
        "redis": asyncio.create_task(_timed("redis", _check_redis(redis), 0.8)),
        "milvus": asyncio.create_task(_timed("milvus", _check_milvus(milvus), 0.8)),
        "minio": asyncio.create_task(_timed("minio", _check_minio(), 0.8)),
    }

    results = {name: await task for name, task in tasks.items()}
    results["checkpointer"] = _status_dependency(CheckpointManager.status())
    results["memory_store"] = _status_dependency(StoreManager.status())
    semantic_cache_service = getattr(resources, "semantic_cache_service", None)
    if semantic_cache_service is not None and hasattr(semantic_cache_service, "status"):
        semantic_cache_status = semantic_cache_service.status()
    else:
        semantic_cache_status = {
            "status": "unknown",
            "enabled": None,
            "backend": "redisvl",
            "reason": "semantic_cache_service_unavailable",
        }
    results["semantic_cache"] = _status_dependency(semantic_cache_status)
    postgres_ok = bool(results.get("postgres", {}).get("ok"))

    if not postgres_ok:
        return JSONResponse(
            status_code=503,
            content=build_error_response(
                code="NOT_READY",
                message="服务未就绪",
                request_id=get_request_id(),
                details={"dependencies": results},
            ),
        )

    degraded = any(not bool(r.get("ok")) for k, r in results.items() if k != "postgres")
    status = "degraded" if degraded else "ready"
    return JSONResponse(
        status_code=200, content={"status": status, "dependencies": results}
    )

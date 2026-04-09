from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Any, Callable

import asyncio
import anyio

try:
    from minio import Minio
    from minio.error import S3Error
except Exception:  # pragma: no cover - optional dependency in lightweight test env
    Minio = None  # type: ignore[assignment]

    class S3Error(Exception):  # type: ignore[no-redef]
        code: str = "Unknown"


from app.core.settings import get_settings


_BUCKET_CACHE: set[str] = set()
_BUCKET_LOCK: asyncio.Lock | None = None
_BUCKET_LOCK_LOOP: asyncio.AbstractEventLoop | None = None


def _is_not_found_error(exc: S3Error) -> bool:
    return exc.code in {"NoSuchKey", "NoSuchBucket"}


def _get_bucket_lock() -> asyncio.Lock:
    global _BUCKET_LOCK, _BUCKET_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _BUCKET_LOCK is None or _BUCKET_LOCK_LOOP is not loop:
        _BUCKET_LOCK = asyncio.Lock()
        _BUCKET_LOCK_LOOP = loop
    return _BUCKET_LOCK


@dataclass(slots=True)
class ObjectRef:
    bucket: str
    object_name: str


class ObjectStorage:
    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        if Minio is None:
            raise RuntimeError("minio dependency is required to use ObjectStorage")

        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    async def _run_client_call(
        self,
        func: Callable[..., Any],
        /,
        *args: object,
        **kwargs: object,
    ) -> Any:
        return await anyio.to_thread.run_sync(partial(func, *args, **kwargs))

    async def ensure_buckets(self) -> None:
        def _ensure(bucket: str) -> None:
            exists = self._client.bucket_exists(bucket)
            if not exists:
                self._client.make_bucket(bucket)

        buckets = {
            self._settings.minio_bucket_uploads,
            self._settings.minio_bucket_exports,
        }
        lock = _get_bucket_lock()
        async with lock:
            pending = [bucket for bucket in buckets if bucket not in _BUCKET_CACHE]
            if not pending:
                return
            for bucket in pending:
                await anyio.to_thread.run_sync(_ensure, bucket)
                _BUCKET_CACHE.add(bucket)

    async def presign_get(self, ref: ObjectRef) -> str:
        expires = timedelta(seconds=self._settings.exports_presign_expire_seconds)
        return await self._run_client_call(
            self._client.presigned_get_object,
            ref.bucket,
            ref.object_name,
            expires=expires,
        )

    async def presign_put(
        self,
        ref: ObjectRef,
        *,
        expires_seconds: int | None = None,
    ) -> str:
        expires = timedelta(
            seconds=expires_seconds
            if expires_seconds is not None
            else self._settings.exports_presign_expire_seconds
        )
        return await self._run_client_call(
            self._client.presigned_put_object,
            ref.bucket,
            ref.object_name,
            expires=expires,
        )

    async def put_text(
        self, ref: ObjectRef, content: str, *, content_type: str = "text/plain"
    ) -> None:
        data = content.encode("utf-8")

        def _put() -> None:
            from io import BytesIO

            self._client.put_object(
                ref.bucket,
                ref.object_name,
                data=BytesIO(data),
                length=len(data),
                content_type=content_type,
            )

        await anyio.to_thread.run_sync(_put)

    async def put_bytes(
        self, ref: ObjectRef, data: bytes, *, content_type: str | None = None
    ) -> None:
        """上传二进制数据到对象存储。"""

        def _put() -> None:
            from io import BytesIO

            self._client.put_object(
                ref.bucket,
                ref.object_name,
                data=BytesIO(data),
                length=len(data),
                content_type=content_type or "application/octet-stream",
            )

        await anyio.to_thread.run_sync(_put)

    async def get_bytes(self, ref: ObjectRef) -> bytes:
        """从对象存储获取二进制数据。"""

        def _get() -> bytes:
            response = self._client.get_object(ref.bucket, ref.object_name)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await anyio.to_thread.run_sync(_get)

    async def get_size(self, ref: ObjectRef) -> int:
        """获取对象大小（字节）。"""

        def _stat() -> int:
            stat = self._client.stat_object(ref.bucket, ref.object_name)
            return int(getattr(stat, "size", 0) or 0)

        return await anyio.to_thread.run_sync(_stat)

    async def exists(self, ref: ObjectRef) -> bool:
        """判断对象是否存在。"""

        def _exists() -> bool:
            self._client.stat_object(ref.bucket, ref.object_name)
            return True

        try:
            return await anyio.to_thread.run_sync(_exists)
        except S3Error as exc:
            if _is_not_found_error(exc):
                return False
            raise

    async def remove_object(
        self, ref: ObjectRef, *, ignore_missing: bool = True
    ) -> None:
        """删除单个对象。"""

        def _remove() -> None:
            self._client.remove_object(ref.bucket, ref.object_name)

        try:
            await anyio.to_thread.run_sync(_remove)
        except S3Error as exc:
            if ignore_missing and _is_not_found_error(exc):
                return
            raise

    async def remove_by_prefix(self, *, bucket: str, prefix: str) -> int:
        """按前缀删除对象，返回删除数量。"""

        def _remove() -> int:
            removed = 0
            for obj in self._client.list_objects(
                bucket_name=bucket,
                prefix=prefix,
                recursive=True,
            ):
                try:
                    self._client.remove_object(bucket, obj.object_name)
                except S3Error as exc:
                    if _is_not_found_error(exc):
                        continue
                    raise
                removed += 1
            return removed

        try:
            return await anyio.to_thread.run_sync(_remove)
        except S3Error as exc:
            if _is_not_found_error(exc):
                return 0
            raise

from __future__ import annotations

from datetime import timedelta

import pytest

from app.integrations import object_storage


class _DummySettings:
    minio_endpoint = "127.0.0.1:9000"
    minio_access_key = "minioadmin"
    minio_secret_key = "minioadmin"
    minio_secure = False
    exports_presign_expire_seconds = 3600


class _FakeMinio:
    def __init__(self, *_args, **_kwargs) -> None:
        self.put_calls: list[tuple[str, str, timedelta]] = []
        self.get_calls: list[tuple[str, str, timedelta]] = []

    def presigned_put_object(
        self,
        bucket_name: str,
        object_name: str,
        expires: timedelta = timedelta(days=7),
    ) -> str:
        self.put_calls.append((bucket_name, object_name, expires))
        return f"put://{bucket_name}/{object_name}?expires={int(expires.total_seconds())}"

    def presigned_get_object(
        self,
        bucket_name: str,
        object_name: str,
        expires: timedelta = timedelta(days=7),
        response_headers: dict[str, str] | None = None,
        request_date: object | None = None,
        version_id: str | None = None,
        extra_query_params: dict[str, str] | None = None,
    ) -> str:
        del response_headers, request_date, version_id, extra_query_params
        self.get_calls.append((bucket_name, object_name, expires))
        return f"get://{bucket_name}/{object_name}?expires={int(expires.total_seconds())}"


@pytest.mark.asyncio
async def test_presign_put_passes_expires_to_minio_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(object_storage, "get_settings", lambda: _DummySettings())
    monkeypatch.setattr(object_storage, "Minio", _FakeMinio)

    storage = object_storage.ObjectStorage()
    ref = object_storage.ObjectRef(bucket="kb", object_name="doc.pdf")

    url = await storage.presign_put(ref, expires_seconds=90)

    assert url == "put://kb/doc.pdf?expires=90"
    assert storage._client.put_calls == [("kb", "doc.pdf", timedelta(seconds=90))]


@pytest.mark.asyncio
async def test_presign_get_passes_expires_to_minio_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(object_storage, "get_settings", lambda: _DummySettings())
    monkeypatch.setattr(object_storage, "Minio", _FakeMinio)

    storage = object_storage.ObjectStorage()
    ref = object_storage.ObjectRef(bucket="exports", object_name="chat.md")

    url = await storage.presign_get(ref)

    assert url == "get://exports/chat.md?expires=3600"
    assert storage._client.get_calls == [("exports", "chat.md", timedelta(seconds=3600))]

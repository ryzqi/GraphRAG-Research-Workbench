from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrations import object_storage as object_storage_module
from app.integrations.object_storage import ObjectRef


class _FakeObjectResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.read_calls: list[int] = []
        self.close_calls = 0
        self.release_calls = 0

    def read(self, size: int) -> bytes:
        self.read_calls.append(size)
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def close(self) -> None:
        self.close_calls += 1

    def release_conn(self) -> None:
        self.release_calls += 1


@pytest.mark.asyncio
async def test_iter_bytes_streams_chunks_and_closes_response() -> None:
    iter_bytes = getattr(object_storage_module.ObjectStorage, "iter_bytes", None)
    assert iter_bytes is not None, "missing ObjectStorage.iter_bytes"

    response = _FakeObjectResponse([b"ab", b"cd", b""])
    storage = object_storage_module.ObjectStorage.__new__(
        object_storage_module.ObjectStorage
    )
    storage._settings = SimpleNamespace()
    storage._client = SimpleNamespace(
        get_object=lambda bucket, object_name: response,
    )
    ref = ObjectRef(bucket="uploads", object_name="docs/file.bin")

    chunks = [chunk async for chunk in storage.iter_bytes(ref, chunk_size=2)]

    assert chunks == [b"ab", b"cd"]
    assert response.read_calls == [2, 2, 2]
    assert response.close_calls == 1
    assert response.release_calls == 1

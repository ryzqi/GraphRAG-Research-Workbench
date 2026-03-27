from __future__ import annotations

import pytest

from app.api.sse import encode_sse


@pytest.mark.asyncio
async def test_encode_sse_propagates_event_producer_exception() -> None:
    async def events():
        yield 'meta', {'ok': True}
        raise RuntimeError('boom')

    stream = encode_sse(events())

    first = await anext(stream)

    assert first == 'event: meta\ndata: {"ok":true}\n\n'

    with pytest.raises(RuntimeError, match='boom'):
        await anext(stream)

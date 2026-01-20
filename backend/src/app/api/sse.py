from __future__ import annotations

import json
from typing import Any, AsyncIterable, AsyncIterator

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _json_dumps(data: Any) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def format_sse(event: str, data: Any) -> str:
    """将事件编码为 SSE 文本。"""
    payload = _json_dumps(data)
    lines = payload.splitlines() or [""]
    return "event: {event}\n".format(event=event) + "".join(
        "data: {line}\n".format(line=line) for line in lines
    ) + "\n"


def format_sse_comment(comment: str) -> str:
    """生成 SSE 注释（心跳）。"""
    return ": {comment}\n\n".format(comment=comment)


async def encode_sse(
    events: AsyncIterable[tuple[str, Any]],
) -> AsyncIterator[str]:
    """将事件序列转换为 SSE 字符串流。"""
    async for event, data in events:
        yield format_sse(event, data)

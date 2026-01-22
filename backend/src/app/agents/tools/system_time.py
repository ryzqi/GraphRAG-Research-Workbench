"""系统时间工具。

提供当前系统时间，支持可选 IANA 时区。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain.tools import BaseTool, tool as lc_tool
from pydantic import BaseModel, Field


class SystemTimeArgs(BaseModel):
    """系统时间参数。"""

    timezone: str | None = Field(
        default=None, description="IANA 时区名称，如 Asia/Shanghai"
    )


def _format_offset(offset: timedelta | None) -> str:
    if offset is None:
        return "UTC+00:00"
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _build_timezone_label(local_time: datetime) -> str:
    tzinfo = local_time.tzinfo
    tz_key = getattr(tzinfo, "key", None)
    tz_name = tz_key or (tzinfo.tzname(local_time) if tzinfo else "UTC")
    offset = _format_offset(local_time.utcoffset())
    if tz_name:
        return f"{tz_name} ({offset})"
    return offset


def build_system_time_tool() -> BaseTool:
    """构建系统时间工具。"""

    async def _get_system_time(timezone: str | None = None) -> str:
        tz_name = (timezone or "").strip()
        tzinfo = None
        if tz_name:
            try:
                tzinfo = ZoneInfo(tz_name)
            except ZoneInfoNotFoundError:
                return json.dumps(
                    {
                        "error": "无效时区，请使用 IANA 时区名称，例如 Asia/Shanghai。",
                        "timezone": tz_name,
                    },
                    ensure_ascii=False,
                )

        now_utc = datetime.now(dt_timezone.utc)
        local_time = now_utc.astimezone(tzinfo) if tzinfo else now_utc.astimezone()

        payload = {
            "local_time": local_time.isoformat(),
            "utc_time": now_utc.isoformat(),
            "timezone": _build_timezone_label(local_time),
            "unix_ts": int(now_utc.timestamp()),
        }
        return json.dumps(payload, ensure_ascii=False)

    return lc_tool(
        "get_system_time",
        description=(
            "获取当前系统时间，支持可选 IANA 时区。返回本地时间、UTC 时间、时区偏移与 Unix 时间戳。"
        ),
        args_schema=SystemTimeArgs,
    )(_get_system_time)

"""Custom uvicorn loop factory helpers for Windows compatibility."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable

from uvicorn.loops.asyncio import asyncio_loop_factory


def windows_selector_loop_factory(
    use_subprocess: bool = False,
) -> Callable[[], asyncio.AbstractEventLoop]:
    """Force SelectorEventLoop on Windows for psycopg async compatibility."""

    if sys.platform == "win32":
        return asyncio.SelectorEventLoop
    return asyncio_loop_factory(use_subprocess=use_subprocess)

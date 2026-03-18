"""Custom uvicorn loop factory helpers for Windows compatibility."""

from __future__ import annotations

import asyncio
import sys


def windows_selector_loop_factory() -> asyncio.AbstractEventLoop:
    """Return a loop instance compatible with uvicorn custom --loop import semantics."""

    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()

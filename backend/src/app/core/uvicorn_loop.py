"""面向 Windows 兼容性的自定义 uvicorn loop factory 辅助函数。"""

from __future__ import annotations

import asyncio
import sys


def windows_selector_loop_factory() -> asyncio.AbstractEventLoop:
    """返回兼容 uvicorn 自定义 --loop 导入语义的事件循环实例。"""

    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()

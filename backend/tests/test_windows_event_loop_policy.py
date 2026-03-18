from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


def test_start_all_uses_custom_windows_selector_loop_factory() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = (repo_root / "scripts" / "start_all.ps1").read_text(encoding="utf-8")

    assert (
        "--loop app.core.uvicorn_loop:windows_selector_loop_factory" in script
    ), script


@pytest.mark.skipif(
    not sys.platform.startswith("win"),
    reason="Windows-specific loop factory regression test",
)
def test_windows_selector_loop_factory_returns_selector_event_loop() -> None:
    from app.core.uvicorn_loop import windows_selector_loop_factory

    loop_factory = windows_selector_loop_factory(use_subprocess=False)
    loop = loop_factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()

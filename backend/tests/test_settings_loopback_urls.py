from __future__ import annotations

import sys

import pytest

from app.core.settings import Settings


@pytest.mark.skipif(
    not sys.platform.startswith("win"),
    reason="Windows-specific localhost normalization test",
)
def test_memory_store_url_prefers_ipv4_loopback_on_windows() -> None:
    settings = Settings(
        MEMORY_STORE_URL="postgresql://mkb:mkb@localhost:5433/mkb",
    )

    assert settings.memory_store_url == "postgresql://mkb:mkb@127.0.0.1:5433/mkb"

from __future__ import annotations

from app.core.settings import Settings
from app.integrations.http_client import create_http_client


def test_create_http_client_uses_environment_proxy_settings() -> None:
    client = create_http_client(Settings())

    try:
        assert client._trust_env is True
    finally:
        if not client.is_closed:
            import asyncio

            asyncio.run(client.aclose())

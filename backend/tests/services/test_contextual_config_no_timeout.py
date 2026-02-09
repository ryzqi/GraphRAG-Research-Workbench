import asyncio

import pytest
from pydantic import ValidationError

from app.schemas.knowledge_bases import IndexConfig
from app.services.contextual_embedding_service import ContextualEmbeddingService


def test_contextual_config_rejects_timeout_seconds() -> None:
    with pytest.raises(ValidationError):
        IndexConfig.model_validate(
            {
                "contextual": {
                    "enabled": True,
                    "timeout_seconds": 15,
                    "max_tokens": 128,
                    "concurrency": 3,
                }
            }
        )


def test_contextual_config_without_timeout_seconds_is_valid() -> None:
    config = IndexConfig.model_validate(
        {
            "contextual": {
                "enabled": True,
                "max_tokens": 128,
                "concurrency": 3,
            }
        }
    )

    assert "timeout_seconds" not in config.contextual.model_dump(mode="json")


@pytest.mark.asyncio
async def test_generate_does_not_use_asyncio_wait_for(monkeypatch) -> None:
    service = ContextualEmbeddingService()
    wait_for_called = False

    async def fake_wait_for(*args, **kwargs):
        nonlocal wait_for_called
        wait_for_called = True
        return await args[0]

    async def fake_call_llm(prompt: str, *, max_tokens: int) -> str:
        await asyncio.sleep(0)
        return "generated context"

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(service, "_call_llm", fake_call_llm)

    result = await service.generate(
        full_text="full text",
        chunk="text",
        enabled=True,
        max_tokens=64,
    )

    assert wait_for_called is False
    assert result.success is True
    assert result.context == "generated context"

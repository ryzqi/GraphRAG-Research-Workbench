from types import SimpleNamespace

import pytest

from app.core.settings import Settings
from app.services import contextual_embedding_service as service_module
from app.worker.tasks.contextual_retry import generate_contexts_for_chunks


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


class _FakeModel:
    def __init__(self, *, text: str) -> None:
        self._text = text

    def invoke(self, _messages):  # noqa: ANN001, ANN201
        return SimpleNamespace(
            content=self._text,
            response_metadata={
                "finish_reason": "stop",
                "token_usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 3,
                },
            },
        )


@pytest.mark.asyncio
async def test_generate_contexts_for_chunks_reuses_chat_model_within_service_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _make_settings(
        ingestion_contextual_enabled=True,
        ingestion_contextual_max_tokens=32,
    )
    created_models: list[_FakeModel] = []

    def _fake_create_chat_model(*, settings: Settings) -> _FakeModel:
        model = _FakeModel(text=f"context-{len(created_models)}")
        created_models.append(model)
        return model

    monkeypatch.setattr(service_module, "create_chat_model", _fake_create_chat_model)

    context_service = service_module.ContextualEmbeddingService(settings=settings)
    chunk_texts = ["chunk-a", "chunk-b", "chunk-c"]

    results = await generate_contexts_for_chunks(
        full_text="chunk-a chunk-b chunk-c",
        chunk_texts=chunk_texts,
        context_service=context_service,
        enabled=True,
        max_tokens=32,
        concurrency=3,
        max_attempts=1,
    )

    assert [item.status for item in results] == ["success", "success", "success"]
    assert [item.context for item in results] == [
        "context-0",
        "context-0",
        "context-0",
    ]
    assert len(created_models) == 1


@pytest.mark.asyncio
async def test_generate_rebuilds_chat_model_when_runtime_version_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _make_settings(
        ingestion_contextual_enabled=True,
        ingestion_contextual_max_tokens=32,
    )
    created_models: list[_FakeModel] = []
    versions = iter([1, 1, 2])

    class _FakeRuntimeConfigManager:
        @classmethod
        def get_snapshot(cls, *, settings=None):  # noqa: ANN001, ANN206
            return SimpleNamespace(version=next(versions))

    def _fake_create_chat_model(*, settings: Settings) -> _FakeModel:
        model = _FakeModel(text=f"context-{len(created_models)}")
        created_models.append(model)
        return model

    monkeypatch.setattr(
        service_module,
        "ModelRuntimeConfigManager",
        _FakeRuntimeConfigManager,
        raising=False,
    )
    monkeypatch.setattr(service_module, "create_chat_model", _fake_create_chat_model)

    context_service = service_module.ContextualEmbeddingService(settings=settings)

    first = await context_service.generate(
        full_text="doc chunk",
        chunk="chunk",
        enabled=True,
        max_tokens=32,
    )
    second = await context_service.generate(
        full_text="doc chunk",
        chunk="chunk",
        enabled=True,
        max_tokens=32,
    )
    third = await context_service.generate(
        full_text="doc chunk",
        chunk="chunk",
        enabled=True,
        max_tokens=32,
    )

    assert first.context == "context-0"
    assert second.context == "context-0"
    assert third.context == "context-1"
    assert len(created_models) == 2

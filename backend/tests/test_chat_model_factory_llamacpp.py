from __future__ import annotations

from app.integrations.chat_model_factory import create_chat_model_from_runtime_config
from app.integrations.llamacpp_chat_model import LlamaCppChatOpenAI
from app.integrations.model_runtime_config import RuntimeProviderConfig
from app.models.model_config import ModelProvider


def test_llamacpp_uses_dedicated_chat_model_without_reasoning() -> None:
    provider_cfg = RuntimeProviderConfig(
        provider=ModelProvider.LLAMA_CPP,
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_key=None,
        models=["gemma-4-e2b-it-Q8_0"],
        thinking_enabled=False,
        thinking_level=None,
    )

    model = create_chat_model_from_runtime_config(
        provider_cfg=provider_cfg,
        model_name="gemma-4-e2b-it-Q8_0",
    )

    assert isinstance(model, LlamaCppChatOpenAI)
    assert model.model_name == "gemma-4-e2b-it-Q8_0"
    assert str(model.openai_api_base) == "http://127.0.0.1:8080/v1"
    assert model.openai_api_key.get_secret_value() == "not-needed"
    assert model.use_responses_api is False
    assert "reasoning" not in model.model_kwargs

from __future__ import annotations

from dataclasses import dataclass

from app.models.model_config import ModelProvider


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider: ModelProvider
    label: str
    base_url_placeholder: str
    base_url_helper_text: str | None
    default_base_url: str | None
    supports_thinking_toggle: bool
    supports_thinking_level: bool
    default_thinking_enabled: bool
    default_thinking_level: str | None
    api_key_optional: bool
    structured_output_method: str | None = None


_PROVIDER_DESCRIPTORS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        provider=ModelProvider.OPENAI,
        label="OpenAI",
        base_url_placeholder="https://api.openai.com/v1",
        base_url_helper_text=None,
        default_base_url=None,
        supports_thinking_toggle=True,
        supports_thinking_level=True,
        default_thinking_enabled=True,
        default_thinking_level="high",
        api_key_optional=False,
        structured_output_method="responses",
    ),
    ProviderDescriptor(
        provider=ModelProvider.OLLAMA,
        label="Ollama",
        base_url_placeholder="http://<ollama-host>:11434",
        base_url_helper_text=None,
        default_base_url=None,
        supports_thinking_toggle=True,
        supports_thinking_level=True,
        default_thinking_enabled=True,
        default_thinking_level="high",
        api_key_optional=True,
        structured_output_method=None,
    ),
    ProviderDescriptor(
        provider=ModelProvider.LLAMA_CPP,
        label="llama.cpp",
        base_url_placeholder="http://<llama-cpp-host>:8080/v1",
        base_url_helper_text="支持填写服务根地址、/v1 或完整 /v1/chat/completions；保存后会规范化为 /v1。",
        default_base_url=None,
        supports_thinking_toggle=False,
        supports_thinking_level=False,
        default_thinking_enabled=False,
        default_thinking_level=None,
        api_key_optional=True,
        structured_output_method=None,
    ),
    ProviderDescriptor(
        provider=ModelProvider.NVIDIA,
        label="NVIDIA",
        base_url_placeholder="https://integrate.api.nvidia.com/v1",
        base_url_helper_text=None,
        default_base_url=None,
        supports_thinking_toggle=True,
        supports_thinking_level=False,
        default_thinking_enabled=True,
        default_thinking_level=None,
        api_key_optional=False,
        structured_output_method="chat_template_kwargs",
    ),
    ProviderDescriptor(
        provider=ModelProvider.ANTHROPIC,
        label="Anthropic",
        base_url_placeholder="https://api.anthropic.com",
        base_url_helper_text="支持填写服务根地址或完整 /v1/messages 地址；保存后会规范化为根地址。",
        default_base_url=None,
        supports_thinking_toggle=True,
        supports_thinking_level=True,
        default_thinking_enabled=True,
        default_thinking_level="high",
        api_key_optional=False,
        structured_output_method="messages",
    ),
)

_PROVIDER_BY_ID = {item.provider: item for item in _PROVIDER_DESCRIPTORS}


def ordered_provider_descriptors() -> tuple[ProviderDescriptor, ...]:
    return _PROVIDER_DESCRIPTORS


def provider_order() -> tuple[ModelProvider, ...]:
    return tuple(item.provider for item in _PROVIDER_DESCRIPTORS)


def get_provider_descriptor(provider: ModelProvider) -> ProviderDescriptor:
    return _PROVIDER_BY_ID[provider]

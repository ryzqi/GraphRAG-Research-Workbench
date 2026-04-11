"""llama.cpp 的 OpenAI 兼容 ChatModel 包装器。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import openai
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai.chat_models.base import (
    ChatOpenAI,
    _convert_delta_to_message_chunk,
    _convert_dict_to_message,
    _create_usage_metadata,
)


def _normalize_reasoning_content(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value
    return normalized if normalized else None


def _inject_reasoning_payload(
    additional_kwargs: dict[str, Any],
    reasoning_content: object,
) -> None:
    normalized = _normalize_reasoning_content(reasoning_content)
    if normalized is None:
        return

    additional_kwargs["reasoning_content"] = normalized
    reasoning = additional_kwargs.get("reasoning")
    if isinstance(reasoning, dict):
        reasoning.setdefault("reasoning", normalized)
        return
    additional_kwargs["reasoning"] = {"reasoning": normalized}


class LlamaCppChatOpenAI(ChatOpenAI):
    """保留 llama.cpp `reasoning_content` 的 ChatOpenAI 子类。"""

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        if chunk.get("type") == "content.delta":
            return None
        token_usage = chunk.get("usage")
        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])

        usage_metadata = (
            _create_usage_metadata(token_usage, chunk.get("service_tier"))
            if token_usage
            else None
        )
        if len(choices) == 0:
            generation_chunk = ChatGenerationChunk(
                message=default_chunk_class(content="", usage_metadata=usage_metadata),
                generation_info=base_generation_info,
            )
            if self.output_version == "v1":
                generation_chunk.message.content = []
                generation_chunk.message.response_metadata["output_version"] = "v1"
            return generation_chunk

        choice = choices[0]
        if choice["delta"] is None:
            return None

        delta = cast("Mapping[str, Any]", choice["delta"])
        message_chunk = _convert_delta_to_message_chunk(delta, default_chunk_class)
        if isinstance(message_chunk, AIMessageChunk):
            _inject_reasoning_payload(
                message_chunk.additional_kwargs,
                delta.get("reasoning_content"),
            )

        generation_info = {**base_generation_info} if base_generation_info else {}

        if finish_reason := choice.get("finish_reason"):
            generation_info["finish_reason"] = finish_reason
            if model_name := chunk.get("model"):
                generation_info["model_name"] = model_name
            if system_fingerprint := chunk.get("system_fingerprint"):
                generation_info["system_fingerprint"] = system_fingerprint
            if service_tier := chunk.get("service_tier"):
                generation_info["service_tier"] = service_tier

        logprobs = choice.get("logprobs")
        if logprobs:
            generation_info["logprobs"] = logprobs

        if usage_metadata and isinstance(message_chunk, AIMessageChunk):
            message_chunk.usage_metadata = usage_metadata

        message_chunk.response_metadata["model_provider"] = "openai"
        return ChatGenerationChunk(
            message=message_chunk,
            generation_info=generation_info or None,
        )

    def _create_chat_result(
        self,
        response: dict | openai.BaseModel,
        generation_info: dict | None = None,
    ) -> ChatResult:
        generations: list[ChatGeneration] = []

        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}}
            )
        )
        if response_dict.get("error"):
            raise ValueError(response_dict.get("error"))

        try:
            choices = response_dict["choices"]
        except KeyError as exc:
            msg = f"Response missing 'choices' key: {response_dict.keys()}"
            raise KeyError(msg) from exc

        if choices is None:
            msg = (
                "Received response with null value for 'choices'. "
                "This can happen when using OpenAI-compatible APIs (e.g., vLLM) "
                "that return a response in an unexpected format. "
                f"Full response keys: {list(response_dict.keys())}"
            )
            raise TypeError(msg)

        token_usage = response_dict.get("usage")
        service_tier = response_dict.get("service_tier")

        for res in choices:
            message = _convert_dict_to_message(res["message"])
            if isinstance(message, AIMessage):
                _inject_reasoning_payload(
                    message.additional_kwargs,
                    res.get("message", {}).get("reasoning_content"),
                )
                if token_usage:
                    message.usage_metadata = _create_usage_metadata(
                        token_usage,
                        service_tier,
                    )
            generation_info = generation_info or {}
            generation_info["finish_reason"] = (
                res.get("finish_reason")
                if res.get("finish_reason") is not None
                else generation_info.get("finish_reason")
            )
            if "logprobs" in res:
                generation_info["logprobs"] = res["logprobs"]
            generations.append(
                ChatGeneration(message=message, generation_info=generation_info)
            )

        llm_output = {
            "token_usage": token_usage,
            "model_provider": "openai",
            "model_name": response_dict.get("model", self.model_name),
            "system_fingerprint": response_dict.get("system_fingerprint", ""),
        }
        if "id" in response_dict:
            llm_output["id"] = response_dict["id"]
        if service_tier:
            llm_output["service_tier"] = service_tier

        if isinstance(response, openai.BaseModel) and getattr(
            response, "choices", None
        ):
            message = response.choices[0].message  # type: ignore[attr-defined]
            if hasattr(message, "parsed"):
                generations[0].message.additional_kwargs["parsed"] = message.parsed
            if hasattr(message, "refusal"):
                generations[0].message.additional_kwargs["refusal"] = message.refusal
            if hasattr(message, "reasoning_content"):
                _inject_reasoning_payload(
                    generations[0].message.additional_kwargs,
                    getattr(message, "reasoning_content"),
                )

        return ChatResult(generations=generations, llm_output=llm_output)

"""Shared ToolStrategy structured-output adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TypeVar

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, ValidationError

_SchemaT = TypeVar("_SchemaT", bound=BaseModel)


@dataclass(slots=True)
class ToolStrategyStructuredResult:
    payload: BaseModel | None
    reason: str | None


def create_tool_strategy_agent(
    *,
    chat_model: object,
    schema: type[_SchemaT],
    system_prompt: str,
) -> object:
    return create_agent(
        model=chat_model,
        tools=[],
        system_prompt=system_prompt,
        response_format=ToolStrategy(schema=schema, handle_errors=True),
    )


def _classify_tool_strategy_error(exc: Exception) -> str:
    name = exc.__class__.__name__
    if name == "StructuredOutputValidationError":
        return "invalid_schema"
    if name == "MultipleStructuredOutputsError":
        return "multiple_structured_outputs"
    return "error"


async def invoke_tool_strategy_structured(
    *,
    schema: type[_SchemaT],
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    chat_model: object | None = None,
    agent: object | None = None,
) -> ToolStrategyStructuredResult:
    _ = max_tokens
    if agent is None:
        if chat_model is None:
            return ToolStrategyStructuredResult(
                payload=None,
                reason="agent_or_model_required",
            )
        agent = create_tool_strategy_agent(
            chat_model=chat_model,
            schema=schema,
            system_prompt=system_prompt,
        )
    request = {"messages": [{"role": "user", "content": user_prompt}]}

    try:
        ainvoke = getattr(agent, "ainvoke", None)
        if callable(ainvoke):
            result = await ainvoke(request)
        else:
            result = await asyncio.to_thread(agent.invoke, request)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return ToolStrategyStructuredResult(
            payload=None,
            reason=_classify_tool_strategy_error(exc),
        )

    if not isinstance(result, dict):
        return ToolStrategyStructuredResult(payload=None, reason="empty_structured_response")

    structured_payload = result.get("structured_response")
    if structured_payload is None:
        return ToolStrategyStructuredResult(payload=None, reason="empty_structured_response")

    if isinstance(structured_payload, schema):
        return ToolStrategyStructuredResult(payload=structured_payload, reason=None)

    try:
        payload = schema.model_validate(structured_payload)
    except ValidationError:
        return ToolStrategyStructuredResult(payload=None, reason="invalid_schema")
    return ToolStrategyStructuredResult(payload=payload, reason=None)

import pytest
from pydantic import BaseModel

from app.agents.kb_chat_agentic import reflection
from app.services.query_rewrite_service import QueryRewriteService


class DemoSchema(BaseModel):
    value: int


class DummyAgent:
    def __init__(self, *, result=None, error=None):
        self._result = result
        self._error = error

    async def ainvoke(self, _request):
        if self._error is not None:
            raise self._error
        return self._result


@pytest.mark.asyncio
async def test_query_rewrite_invoke_structured_success_and_validate_dict():
    svc = QueryRewriteService.__new__(QueryRewriteService)

    parsed = await svc._invoke_structured(
        agent=DummyAgent(result={"structured_response": DemoSchema(value=1)}),
        schema=DemoSchema,
        user_prompt="prompt",
        max_tokens=32,
    )
    assert parsed.success is True
    assert isinstance(parsed.payload, DemoSchema)
    assert parsed.payload.value == 1
    assert parsed.reason is None

    validated = await svc._invoke_structured(
        agent=DummyAgent(result={"structured_response": {"value": 2}}),
        schema=DemoSchema,
        user_prompt="prompt",
        max_tokens=32,
    )
    assert validated.success is True
    assert isinstance(validated.payload, DemoSchema)
    assert validated.payload.value == 2
    assert validated.reason is None


@pytest.mark.asyncio
async def test_query_rewrite_invoke_structured_reason_mapping():
    svc = QueryRewriteService.__new__(QueryRewriteService)

    empty = await svc._invoke_structured(
        agent=DummyAgent(result={}),
        schema=DemoSchema,
        user_prompt="prompt",
        max_tokens=32,
    )
    assert empty.success is False
    assert empty.reason == "empty_structured_response"

    invalid = await svc._invoke_structured(
        agent=DummyAgent(result={"structured_response": {"bad": "x"}}),
        schema=DemoSchema,
        user_prompt="prompt",
        max_tokens=32,
    )
    assert invalid.success is False
    assert invalid.reason == "invalid_schema"

    multiple_error = type("MultipleStructuredOutputsError", (Exception,), {})("boom")
    multiple = await svc._invoke_structured(
        agent=DummyAgent(error=multiple_error),
        schema=DemoSchema,
        user_prompt="prompt",
        max_tokens=32,
    )
    assert multiple.success is False
    assert multiple.reason == "multiple_structured_outputs"


@pytest.mark.asyncio
async def test_reflection_judge_structured_success_and_invalid(monkeypatch):
    monkeypatch.setattr(
        reflection,
        "create_agent",
        lambda **_: DummyAgent(result={"structured_response": {"value": 3}}),
    )
    payload, reason = await reflection._judge_structured(
        chat_model=object(),
        schema=DemoSchema,
        system="sys",
        user="user",
    )
    assert isinstance(payload, DemoSchema)
    assert payload.value == 3
    assert reason is None

    monkeypatch.setattr(
        reflection,
        "create_agent",
        lambda **_: DummyAgent(result={"structured_response": {"bad": 1}}),
    )
    payload, reason = await reflection._judge_structured(
        chat_model=object(),
        schema=DemoSchema,
        system="sys",
        user="user",
    )
    assert payload is None
    assert reason == "invalid_schema"


@pytest.mark.asyncio
async def test_reflection_judge_structured_error_reason(monkeypatch):
    generic_error = RuntimeError("boom")
    monkeypatch.setattr(
        reflection,
        "create_agent",
        lambda **_: DummyAgent(error=generic_error),
    )
    payload, reason = await reflection._judge_structured(
        chat_model=object(),
        schema=DemoSchema,
        system="sys",
        user="user",
    )
    assert payload is None
    assert reason == "error"

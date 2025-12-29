import pytest
from pydantic import ValidationError

from app.agents.mcp_tools import _build_args_schema
from app.integrations.mcp_client import ToolDefinition


def test_build_args_schema_required_field() -> None:
    tool = ToolDefinition(
        name="demo_tool",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )

    schema = _build_args_schema(tool)
    assert schema is not None
    schema(query="hello")
    with pytest.raises(ValidationError):
        schema()

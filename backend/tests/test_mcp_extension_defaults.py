from __future__ import annotations

from app.core.settings import Settings
from app.integrations.mcp_adapters import build_mcp_server_params
from app.models.tool_extension import ExtensionStatus, ExtensionTransport, ToolExtension
from app.schemas.extensions import ExtensionStatus as SchemaExtensionStatus
from app.schemas.extensions import ToolExtensionCreate


def test_extension_create_defaults_to_enabled_without_security_config() -> None:
    payload = {
        "name": "demo-extension",
        "transport": "http",
        "http_config": {
            "url": "http://127.0.0.1:8001/mcp",
            "protocol": "streamable_http",
            "headers": {},
            "auth": {"type": "none"},
        },
    }

    model = ToolExtensionCreate.model_validate(payload)
    assert model.status == SchemaExtensionStatus.ENABLED


def test_stdio_template_allows_custom_command_without_whitelist() -> None:
    settings = Settings(
        mcp_stdio_templates={
            "custom": {
                "command": "my-custom-mcp",
                "args": ["--base"],
                "env": {"BASE_ENV": "1"},
            }
        }
    )
    extension = ToolExtension(
        name="custom-stdio",
        transport=ExtensionTransport.STDIO,
        status=ExtensionStatus.ENABLED,
        http_config=None,
        stdio_config={
            "template_id": "custom",
            "args": ["--user"],
            "env": {"USER_ENV": "2"},
        },
        observability_config=None,
    )

    params = build_mcp_server_params(extension, settings)
    assert params["command"] == "my-custom-mcp"
    assert params["args"] == ["--base", "--user"]
    assert params["env"] == {"BASE_ENV": "1", "USER_ENV": "2"}

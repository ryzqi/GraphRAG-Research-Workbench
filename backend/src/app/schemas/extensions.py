"""扩展管理相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.pagination import PageMeta


class ExtensionTransport(str, Enum):
    STDIO = "stdio"
    HTTP = "http"


class ExtensionStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class ExtensionHttpProtocol(str, Enum):
    STREAMABLE_HTTP = "streamable_http"


class ExtensionAuthType(str, Enum):
    NONE = "none"
    BEARER = "bearer"
    BASIC = "basic"


class ExtensionConnectionStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"


class HttpAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ExtensionAuthType = ExtensionAuthType.NONE
    token: str | None = Field(None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def _validate_auth(self) -> "HttpAuthConfig":
        if self.type == ExtensionAuthType.NONE:
            return self
        if not self.token:
            raise ValueError("auth.token is required for bearer/basic authentication")
        return self


class ExtensionHttpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., min_length=1, max_length=2048)
    protocol: ExtensionHttpProtocol = ExtensionHttpProtocol.STREAMABLE_HTTP
    headers: dict[str, str] = Field(default_factory=dict)
    auth: HttpAuthConfig = Field(
        default_factory=lambda: HttpAuthConfig(
            type=ExtensionAuthType.NONE,
            token=None,
        )
    )
    timeout_seconds: int | None = Field(None, ge=1, le=600)

    @model_validator(mode="after")
    def _validate_url(self) -> "ExtensionHttpConfig":
        url = self.url.strip().lower()
        if not url.startswith(("http://", "https://")):
            raise ValueError("http_config.url must start with http:// or https://")
        return self


class ExtensionStdioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(..., min_length=1, max_length=512)
    args: list[str] = Field(default_factory=list, max_length=64)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = Field(None, min_length=1, max_length=2048)
    timeout_seconds: int | None = Field(None, ge=1, le=600)

    @model_validator(mode="after")
    def _validate_command(self) -> "ExtensionStdioConfig":
        command = self.command.strip()
        if not command:
            raise ValueError("stdio_config.command is required")
        self.command = command
        if self.cwd is not None:
            cwd = self.cwd.strip()
            self.cwd = cwd or None
        return self


class ToolExtensionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    transport: ExtensionTransport
    status: ExtensionStatus = ExtensionStatus.ENABLED
    http_config: ExtensionHttpConfig | None = None
    stdio_config: ExtensionStdioConfig | None = None

    @model_validator(mode="after")
    def _validate_transport_config(self) -> "ToolExtensionCreate":
        if self.transport == ExtensionTransport.HTTP and self.http_config is None:
            raise ValueError("http_config is required when transport=http")
        if self.transport == ExtensionTransport.STDIO and self.stdio_config is None:
            raise ValueError("stdio_config is required when transport=stdio")
        if self.transport == ExtensionTransport.HTTP:
            self.stdio_config = None
        if self.transport == ExtensionTransport.STDIO:
            self.http_config = None
        return self


class ToolExtensionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=128)
    transport: ExtensionTransport | None = None
    status: ExtensionStatus | None = None
    http_config: ExtensionHttpConfig | None = None
    stdio_config: ExtensionStdioConfig | None = None


class ToolExtensionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    transport: ExtensionTransport
    status: ExtensionStatus
    http_config: ExtensionHttpConfig | None = None
    stdio_config: ExtensionStdioConfig | None = None
    created_at: datetime
    updated_at: datetime


class ToolDescriptor(BaseModel):
    name: str
    description: str | None = None
    input_schema: dict | None = None


class ToolExtensionListResponse(BaseModel):
    """扩展列表响应。"""

    items: list[ToolExtensionRead]
    page: PageMeta


class ToolDescriptorListResponse(BaseModel):
    """扩展工具列表响应。"""

    items: list[ToolDescriptor]
    page: PageMeta
    connection_status: ExtensionConnectionStatus = ExtensionConnectionStatus.OK
    last_error: str | None = None
    latency_ms: int | None = None

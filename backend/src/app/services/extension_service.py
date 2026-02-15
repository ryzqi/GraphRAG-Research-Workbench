"""扩展管理服务。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, bad_request
from app.core.settings import get_settings
from app.integrations.mcp_adapters import (
    load_mcp_tools,
    load_mcp_tools_with_diagnostics,
    tool_input_schema,
)
from app.models.tool_extension import ExtensionStatus, ExtensionTransport, ToolExtension
from app.schemas.extensions import (
    ExtensionConnectionStatus,
    ExtensionHttpConfig,
    ExtensionSecurityConfig,
    ExtensionStdioConfig,
    ToolDescriptor,
    ToolExtensionCreate,
    ToolExtensionRead,
    ToolExtensionUpdate,
)


def _is_extension_name_conflict_error(exc: IntegrityError) -> bool:
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate == "23505":
        return True

    message = str(orig or exc).lower()
    return "tool_extensions_name_key" in message or (
        "duplicate" in message and "tool_extensions" in message and "name" in message
    )


class ExtensionService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._settings = get_settings()

    async def list_extensions(
        self, *, status: ExtensionStatus | None = None
    ) -> list[ToolExtensionRead]:
        """获取扩展列表。"""
        stmt = select(ToolExtension).order_by(ToolExtension.created_at.desc())
        if status:
            stmt = stmt.where(ToolExtension.status == status)

        result = await self._db.execute(stmt)
        extensions = result.scalars().all()
        return [ToolExtensionRead.model_validate(e) for e in extensions]

    async def list_extensions_page(
        self,
        *,
        status: ExtensionStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[ToolExtensionRead], int]:
        """分页获取扩展列表。"""
        count_stmt = select(func.count()).select_from(ToolExtension)
        if status:
            count_stmt = count_stmt.where(ToolExtension.status == status)
        total = int((await self._db.execute(count_stmt)).scalar_one())

        stmt = (
            select(ToolExtension)
            .order_by(ToolExtension.created_at.desc(), ToolExtension.id.desc())
            .offset(skip)
            .limit(limit)
        )
        if status:
            stmt = stmt.where(ToolExtension.status == status)

        result = await self._db.execute(stmt)
        extensions = result.scalars().all()
        return [ToolExtensionRead.model_validate(e) for e in extensions], total

    async def get_extension(self, extension_id: uuid.UUID) -> ToolExtensionRead | None:
        """获取单个扩展。"""
        ext = await self._db.get(ToolExtension, extension_id)
        return ToolExtensionRead.model_validate(ext) if ext else None

    async def create_extension(self, data: ToolExtensionCreate) -> ToolExtensionRead:
        """创建扩展。"""
        http_config, stdio_config, security_config = self._resolve_transport_configs(
            transport=ExtensionTransport(data.transport.value),
            http_config=data.http_config,
            stdio_config=data.stdio_config,
            security_config=data.security_config,
        )
        ext = ToolExtension(
            name=data.name.strip(),
            transport=ExtensionTransport(data.transport.value),
            status=ExtensionStatus(data.status.value),
            http_config=http_config.model_dump(mode="json") if http_config else None,
            stdio_config=stdio_config.model_dump(mode="json") if stdio_config else None,
            security_config=security_config.model_dump(mode="json"),
            observability_config=(
                data.observability_config.model_dump(mode="json")
                if data.observability_config
                else None
            ),
        )
        self._db.add(ext)

        try:
            await self._db.commit()
        except IntegrityError as exc:
            await self._db.rollback()
            if _is_extension_name_conflict_error(exc):
                raise AppError(
                    code="EXTENSION_NAME_EXISTS",
                    message="扩展名称已存在",
                    status_code=409,
                ) from exc
            raise

        await self._db.refresh(ext)
        return ToolExtensionRead.model_validate(ext)

    async def update_extension(
        self, extension_id: uuid.UUID, data: ToolExtensionUpdate
    ) -> ToolExtensionRead | None:
        """更新扩展。"""
        ext = await self._db.get(ToolExtension, extension_id)
        if not ext:
            return None

        update_data = data.model_dump(exclude_unset=True, mode="python")
        target_transport = ExtensionTransport(
            (
                update_data.get("transport").value
                if update_data.get("transport") is not None
                else ext.transport.value
            )
        )
        target_http = (
            update_data.get("http_config")
            if "http_config" in update_data
            else ext.http_config
        )
        target_stdio = (
            update_data.get("stdio_config")
            if "stdio_config" in update_data
            else ext.stdio_config
        )
        target_security = (
            update_data.get("security_config")
            if "security_config" in update_data
            else ext.security_config
        )

        http_config, stdio_config, security_config = self._resolve_transport_configs(
            transport=target_transport,
            http_config=target_http,
            stdio_config=target_stdio,
            security_config=target_security,
        )

        ext.transport = target_transport
        if "name" in update_data and isinstance(update_data.get("name"), str):
            ext.name = update_data["name"].strip()
        if "status" in update_data and update_data.get("status") is not None:
            ext.status = ExtensionStatus(update_data["status"].value)
        ext.http_config = http_config.model_dump(mode="json") if http_config else None
        ext.stdio_config = stdio_config.model_dump(mode="json") if stdio_config else None
        ext.security_config = security_config.model_dump(mode="json")
        if "observability_config" in update_data:
            obs = update_data.get("observability_config")
            ext.observability_config = (
                obs.model_dump(mode="json") if hasattr(obs, "model_dump") else obs
            )

        try:
            await self._db.commit()
        except IntegrityError as exc:
            await self._db.rollback()
            if _is_extension_name_conflict_error(exc):
                raise AppError(
                    code="EXTENSION_NAME_EXISTS",
                    message="扩展名称已存在",
                    status_code=409,
                ) from exc
            raise

        await self._db.refresh(ext)
        return ToolExtensionRead.model_validate(ext)

    async def delete_extension(self, extension_id: uuid.UUID) -> bool:
        """删除扩展。"""
        ext = await self._db.get(ToolExtension, extension_id)
        if not ext:
            return False
        await self._db.delete(ext)
        await self._db.commit()
        return True

    async def get_tools(self, extension_id: uuid.UUID) -> tuple[
        list[ToolDescriptor],
        ExtensionConnectionStatus,
        str | None,
        int | None,
    ]:
        """获取扩展提供的工具列表。"""
        ext = await self._db.get(ToolExtension, extension_id)
        if not ext:
            return [], ExtensionConnectionStatus.FAILED, "扩展不存在", None
        if ext.status != ExtensionStatus.ENABLED:
            return [], ExtensionConnectionStatus.DEGRADED, "扩展未启用", None

        tools, diagnostics = await load_mcp_tools_with_diagnostics(
            settings=self._settings,
            extensions=[ext],
        )
        per_server = diagnostics.get(str(ext.id))
        items = [
            ToolDescriptor(
                name=t.raw_tool_name,
                description=getattr(t.tool, "description", None),
                input_schema=tool_input_schema(t.tool),
            )
            for t in tools
        ]
        if per_server is None:
            return items, ExtensionConnectionStatus.FAILED, "MCP 连接未建立", None
        return (
            items,
            ExtensionConnectionStatus(per_server.status),
            per_server.last_error,
            per_server.latency_ms,
        )

    async def get_tools_page(
        self,
        extension_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[ToolDescriptor], int, ExtensionConnectionStatus, str | None, int | None]:
        """分页获取扩展提供的工具列表。"""
        tools, status, last_error, latency_ms = await self.get_tools(extension_id)
        tools_sorted = sorted(tools, key=lambda t: t.name)
        total = len(tools_sorted)
        return tools_sorted[skip : skip + limit], total, status, last_error, latency_ms

    async def get_all_enabled_tools(self) -> dict[uuid.UUID, list[ToolDescriptor]]:
        """获取所有启用扩展的工具。"""
        stmt = select(ToolExtension).where(
            ToolExtension.status == ExtensionStatus.ENABLED
        )
        result = await self._db.execute(stmt)
        extensions = result.scalars().all()

        tools_map: dict[uuid.UUID, list[ToolDescriptor]] = {}
        if not extensions:
            return tools_map

        entries = await load_mcp_tools(settings=self._settings, extensions=extensions)
        for entry in entries:
            tool = ToolDescriptor(
                name=entry.raw_tool_name,
                description=getattr(entry.tool, "description", None),
                input_schema=tool_input_schema(entry.tool),
            )
            tools_map.setdefault(entry.extension.id, []).append(tool)

        return tools_map

    def _resolve_transport_configs(
        self,
        *,
        transport: ExtensionTransport,
        http_config: ExtensionHttpConfig | dict | None,
        stdio_config: ExtensionStdioConfig | dict | None,
        security_config: ExtensionSecurityConfig | dict | None,
    ) -> tuple[ExtensionHttpConfig | None, ExtensionStdioConfig | None, ExtensionSecurityConfig]:
        parsed_http = self._parse_http_config(http_config) if http_config is not None else None
        parsed_stdio = (
            self._parse_stdio_config(stdio_config) if stdio_config is not None else None
        )
        parsed_security = self._parse_security_config(security_config)

        if transport == ExtensionTransport.HTTP and parsed_http is None:
            raise bad_request(
                code="HTTP_CONFIG_REQUIRED",
                message="transport=http 时必须提供 http_config",
            )
        if transport == ExtensionTransport.STDIO and parsed_stdio is None:
            raise bad_request(
                code="STDIO_CONFIG_REQUIRED",
                message="transport=stdio 时必须提供 stdio_config",
            )
        if (
            transport == ExtensionTransport.HTTP
            and parsed_http is not None
            and parsed_http.protocol.value != "streamable_http"
        ):
            raise bad_request(
                code="HTTP_PROTOCOL_UNSUPPORTED",
                message="仅支持 streamable_http 协议",
            )
        if transport == ExtensionTransport.HTTP:
            parsed_stdio = None
        if transport == ExtensionTransport.STDIO:
            parsed_http = None

        return parsed_http, parsed_stdio, parsed_security

    @staticmethod
    def _parse_http_config(
        value: ExtensionHttpConfig | dict,
    ) -> ExtensionHttpConfig:
        if isinstance(value, ExtensionHttpConfig):
            return value
        return ExtensionHttpConfig.model_validate(value)

    @staticmethod
    def _parse_stdio_config(
        value: ExtensionStdioConfig | dict,
    ) -> ExtensionStdioConfig:
        if isinstance(value, ExtensionStdioConfig):
            return value
        return ExtensionStdioConfig.model_validate(value)

    @staticmethod
    def _parse_security_config(
        value: ExtensionSecurityConfig | dict | None,
    ) -> ExtensionSecurityConfig:
        if isinstance(value, ExtensionSecurityConfig):
            return value
        if value is None:
            raise bad_request(
                code="SECURITY_CONFIG_REQUIRED",
                message="security_config 为必填项",
            )
        return ExtensionSecurityConfig.model_validate(value)

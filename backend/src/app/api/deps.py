from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.core.settings import get_settings
from app.db.session import get_db_session

AsyncSessionDep = Annotated[AsyncSession, Depends(get_db_session)]

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> str:
    """验证访问凭证，返回用户标识。

    支持两种方式：
    1) Authorization: Bearer <JWT>
    2) X-Admin-Token: <ADMIN_TOKEN>（便于本项目本地演示/集成）
    """
    settings = get_settings()

    if credentials:
        payload = decode_token(credentials.credentials)
        if payload:
            return payload.sub

    if x_admin_token and x_admin_token == settings.admin_token:
        return "admin"

    if credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "无效的认证令牌"},
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "MISSING_TOKEN", "message": "缺少认证令牌"},
    )


CurrentUserDep = Annotated[str, Depends(verify_token)]


async def verify_admin_token(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """验证内部管理 token。"""
    settings = get_settings()
    if not x_admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "MISSING_ADMIN_TOKEN", "message": "缺少管理 token"},
        )
    if x_admin_token != settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "INVALID_ADMIN_TOKEN", "message": "无效的管理 token"},
        )


AdminTokenDep = Annotated[None, Depends(verify_admin_token)]

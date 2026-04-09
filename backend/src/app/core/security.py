"""JWT 身份认证模块。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from pydantic import BaseModel

from app.core.settings import get_settings


class TokenPayload(BaseModel):
    """JWT 载荷。"""

    sub: str
    exp: datetime


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """创建访问令牌。"""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_token(token: str) -> TokenPayload | None:
    """解码并验证令牌。"""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        return TokenPayload(**payload)
    except jwt.PyJWTError:
        return None

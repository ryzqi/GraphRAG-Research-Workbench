"""分页相关 Schemas。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PageMeta(BaseModel):
    """分页元信息。"""

    skip: int = Field(..., ge=0, description="跳过记录数")
    limit: int = Field(..., ge=1, le=100, description="返回记录数")
    total: int = Field(..., ge=0, description="满足条件的总记录数（精确）")
    has_more: bool = Field(..., description="是否还有下一页")


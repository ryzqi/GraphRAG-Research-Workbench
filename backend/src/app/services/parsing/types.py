from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from app.models.source_material import SourceMaterial


@dataclass(slots=True)
class ParsedChunk:
    """解析器产出的 chunk（可能携带块级定位信息）。"""

    text: str
    locator: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class ParsedDocument:
    """解析后的文档结构。"""

    text: str
    mime_type: str | None = None
    locator: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    chunks: list[ParsedChunk] | None = None


class DocumentParser(Protocol):
    """统一解析接口（便于替换实现与单测注入）。"""

    async def parse(self, material: "SourceMaterial") -> ParsedDocument:
        ...

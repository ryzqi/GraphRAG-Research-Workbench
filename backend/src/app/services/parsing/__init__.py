"""资料解析层：将 SourceMaterial 解析为结构化 ParsedDocument。"""

from app.services.parsing.errors import ParseError
from app.services.parsing.material_parser import parse_material
from app.services.parsing.types import DocumentParser, ParsedChunk, ParsedDocument

__all__ = [
    "ParseError",
    "ParsedChunk",
    "ParsedDocument",
    "DocumentParser",
    "parse_material",
]

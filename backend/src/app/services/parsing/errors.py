from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ParseError(Exception):
    """可诊断的解析错误（用于导入任务 stage=parse 统计与排障）。"""

    error_code: str
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.error_code}: {self.message}"

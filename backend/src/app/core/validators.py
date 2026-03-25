"""文件验证器。"""

from __future__ import annotations

from fastapi import HTTPException, status

# 文件大小上限（50MB）
MAX_FILE_SIZE = 50 * 1024 * 1024

# 允许的 MIME 类型白名单（规范化后）
ALLOWED_MIME_TYPES = frozenset({
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
})

# MIME 类型别名归一化
MIME_TYPE_ALIASES = {
    "text/x-markdown": "text/markdown",
    "application/x-pdf": "application/pdf",
}

# 浏览器在无法识别类型时常见的兜底 MIME，需结合扩展名校验放行
GENERIC_MIME_TYPES = frozenset({
    "application/octet-stream",
    "binary/octet-stream",
})

# 允许的文件扩展名
ALLOWED_EXTENSIONS = frozenset({".pdf", ".txt", ".md", ".docx"})


def _normalize_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None

    normalized = content_type.split(";", 1)[0].strip().lower()
    if not normalized:
        return None

    return MIME_TYPE_ALIASES.get(normalized, normalized)


def validate_file_upload(
    content: bytes,
    filename: str,
    content_type: str | None,
) -> None:
    """验证上传文件的大小和类型。"""
    # 校验文件大小
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"code": "FILE_TOO_LARGE", "message": f"文件大小超过限制 ({MAX_FILE_SIZE // 1024 // 1024}MB)"},
        )

    # 校验文件扩展名
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "INVALID_FILE_TYPE", "message": f"不支持的文件类型: {ext}"},
        )

    # 校验 MIME 类型
    normalized_content_type = _normalize_content_type(content_type)
    if (
        normalized_content_type
        and normalized_content_type not in GENERIC_MIME_TYPES
        and normalized_content_type not in ALLOWED_MIME_TYPES
    ):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "INVALID_MIME_TYPE", "message": f"不支持的 MIME 类型: {content_type}"},
        )

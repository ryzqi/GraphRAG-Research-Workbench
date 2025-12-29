"""文件验证器。"""

from __future__ import annotations

from fastapi import HTTPException, status

# 文件大小限制 (100MB)
MAX_FILE_SIZE = 100 * 1024 * 1024

# 允许的 MIME 类型白名单
ALLOWED_MIME_TYPES = frozenset({
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
})

# 允许的文件扩展名
ALLOWED_EXTENSIONS = frozenset({".pdf", ".txt", ".md", ".doc", ".docx"})


def validate_file_upload(
    content: bytes,
    filename: str,
    content_type: str | None,
) -> None:
    """验证上传文件的大小和类型。"""
    # 检查文件大小
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "FILE_TOO_LARGE", "message": f"文件大小超过限制 ({MAX_FILE_SIZE // 1024 // 1024}MB)"},
        )

    # 检查文件扩展名
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "INVALID_FILE_TYPE", "message": f"不支持的文件类型: {ext}"},
        )

    # 检查 MIME 类型
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "INVALID_MIME_TYPE", "message": f"不支持的 MIME 类型: {content_type}"},
        )

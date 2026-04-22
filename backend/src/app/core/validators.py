"""文件验证器。"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.services.upload_policy import (
    ALLOWED_UPLOAD_EXTENSIONS,
    ALLOWED_UPLOAD_MIME_TYPES,
    GENERIC_UPLOAD_MIME_TYPES,
    MAX_UPLOAD_FILE_SIZE_BYTES,
    normalize_upload_content_type,
)


def validate_file_upload(
    content: bytes,
    filename: str,
    content_type: str | None,
) -> None:
    """验证上传文件的大小和类型。"""
    # 校验文件大小
    if len(content) > MAX_UPLOAD_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": f"文件大小超过限制 ({MAX_UPLOAD_FILE_SIZE_BYTES // 1024 // 1024}MB)",
            },
        )

    # 校验文件扩展名
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "INVALID_FILE_TYPE", "message": f"不支持的文件类型: {ext}"},
        )

    # 校验 MIME 类型
    normalized_content_type = normalize_upload_content_type(content_type)
    if (
        normalized_content_type
        and normalized_content_type not in GENERIC_UPLOAD_MIME_TYPES
        and normalized_content_type not in ALLOWED_UPLOAD_MIME_TYPES
    ):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "INVALID_MIME_TYPE",
                "message": f"不支持的 MIME 类型: {content_type}",
            },
        )

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.errors import AppError


@dataclass(frozen=True)
class ErrorSpec:
    http_status: int
    retryable: bool
    message: str
    message_key: str


INGESTION_ERROR_SPECS: dict[str, ErrorSpec] = {
    "MANIFEST_LIMIT_EXCEEDED": ErrorSpec(
        http_status=400,
        retryable=False,
        message="提交条目数超过上限",
        message_key="ingestion.manifest.limit_exceeded",
    ),
    "TEXT_LENGTH_INVALID": ErrorSpec(
        http_status=400,
        retryable=False,
        message="文本长度不在允许范围内",
        message_key="ingestion.text.length_invalid",
    ),
    "URL_SCHEME_NOT_ALLOWED": ErrorSpec(
        http_status=400,
        retryable=False,
        message="URL 协议仅支持 http/https",
        message_key="ingestion.url.scheme_not_allowed",
    ),
    "URL_SSRF_BLOCKED": ErrorSpec(
        http_status=400,
        retryable=False,
        message="URL 被 SSRF 防护策略拦截",
        message_key="ingestion.url.ssrf_blocked",
    ),
    "FILE_TYPE_NOT_ALLOWED": ErrorSpec(
        http_status=400,
        retryable=False,
        message="文件类型不支持",
        message_key="ingestion.file.type_not_allowed",
    ),
    "FILE_SIZE_EXCEEDED": ErrorSpec(
        http_status=400,
        retryable=False,
        message="文件大小超过上限",
        message_key="ingestion.file.size_exceeded",
    ),
    "MANIFEST_ALL_ENTRIES_FAILED": ErrorSpec(
        http_status=400,
        retryable=False,
        message="所有条目都校验失败",
        message_key="ingestion.manifest.all_entries_failed",
    ),
    "BATCH_NOT_FOUND": ErrorSpec(
        http_status=404,
        retryable=False,
        message="批次不存在",
        message_key="ingestion.batch.not_found",
    ),
    "BATCH_STATUS_CONFLICT": ErrorSpec(
        http_status=409,
        retryable=False,
        message="批次状态不允许当前操作",
        message_key="ingestion.batch.status_conflict",
    ),
    "DOC_RETRY_NOT_ALLOWED": ErrorSpec(
        http_status=409,
        retryable=False,
        message="文档当前状态不允许重试",
        message_key="ingestion.doc.retry_not_allowed",
    ),
    "DOC_RETRY_LIMIT_REACHED": ErrorSpec(
        http_status=409,
        retryable=False,
        message="文档重试次数已达上限",
        message_key="ingestion.doc.retry_limit_reached",
    ),
    "KB_NOT_FOUND": ErrorSpec(
        http_status=404,
        retryable=False,
        message="知识库不存在",
        message_key="kb.not_found",
    ),
    "KB_NOT_READY": ErrorSpec(
        http_status=409,
        retryable=False,
        message="知识库尚未就绪",
        message_key="kb.not_ready",
    ),
    "KB_NOT_SELECTABLE": ErrorSpec(
        http_status=409,
        retryable=False,
        message="知识库不可被业务入口选择",
        message_key="kb.not_selectable",
    ),
    "KB_BOOTSTRAP_CONFLICT": ErrorSpec(
        http_status=409,
        retryable=True,
        message="首批批次并发冲突，请重试",
        message_key="kb.bootstrap.conflict",
    ),
    "IDEMPOTENCY_DUPLICATE": ErrorSpec(
        http_status=200,
        retryable=False,
        message="幂等键重复，条目已被处理",
        message_key="ingestion.idempotency.duplicate",
    ),
}


def ingestion_error(
    code: str,
    *,
    message: str | None = None,
    details: dict[str, Any] | None = None,
    status_code: int | None = None,
) -> AppError:
    spec = INGESTION_ERROR_SPECS.get(code)
    resolved_status = status_code or (spec.http_status if spec else 400)
    resolved_message = message or (spec.message if spec else code)

    payload_details = dict(details or {})
    if spec is not None:
        payload_details.setdefault("retryable", spec.retryable)
        payload_details.setdefault("message_key", spec.message_key)

    return AppError(
        code=code,
        message=resolved_message,
        status_code=resolved_status,
        details=payload_details or None,
    )

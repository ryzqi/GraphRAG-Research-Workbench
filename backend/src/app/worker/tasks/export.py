from __future__ import annotations

import json
import uuid

from app.core.errors import AppError
from app.core.settings import get_settings
from app.integrations.object_storage import ObjectRef
from app.models.export_job import ExportJob, ExportStatus
from app.services.exporters.chat_exporter import ChatExporter
from app.services.exporters.research_exporter import ResearchExporter
from app.worker.async_runtime import run_in_worker_async_runtime
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources


def _should_skip_export_job_status(status: ExportStatus) -> bool:
    """仅排队中的作业允许进入任务执行阶段。"""
    return status is not ExportStatus.QUEUED


def _build_download_response_headers(
    *,
    export_type: str,
    target_id: uuid.UUID,
    content_type: str,
    file_extension: str,
) -> dict[str, str] | None:
    if export_type != "research":
        return None

    filename = f"research-report-{target_id}.{file_extension}"
    return {
        "response-content-type": content_type,
        "response-content-disposition": f'attachment; filename="{filename}"',
    }


@celery_app.task(name="app.worker.tasks.export.run_export")
def run_export(export_id: str, export_type: str, target_id: str) -> None:
    run_in_worker_async_runtime(
        _run_export(export_id=export_id, export_type=export_type, target_id=target_id)
    )


async def _run_export(*, export_id: str, export_type: str, target_id: str) -> None:
    settings = get_settings()
    export_uuid = uuid.UUID(export_id)
    target_uuid = uuid.UUID(target_id)

    async with managed_task_resources(
        settings=settings,
        with_engine=True,
        with_object_storage=True,
    ) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover - defensive
            return
        async with sessionmaker() as session:
            job = await session.get(ExportJob, export_uuid)
            if job is None:
                return
            if _should_skip_export_job_status(job.status):
                return

            job.status = ExportStatus.RUNNING
            job.error_message = None
            await session.commit()

            try:
                storage = resources.object_storage
                if storage is None:  # pragma: no cover - defensive
                    raise RuntimeError("共享 object_storage 未初始化")
                await storage.ensure_buckets()

                # 根据类型选择导出器
                if export_type == "chat":
                    exporter = ChatExporter()
                    content = await exporter.export(session, target_uuid)
                    content_type = "text/markdown; charset=utf-8"
                    ext = "md"
                elif export_type == "research":
                    exporter = ResearchExporter()
                    content = await exporter.export(session, target_uuid)
                    content_type = "application/pdf"
                    ext = "pdf"
                else:
                    # 默认占位导出
                    content = (
                        f"导出占位文件。\n"
                        f"type={export_type}\n"
                        f"target_id={target_id}\n"
                        f"export_id={export_id}\n"
                    )
                    content_type = "text/plain; charset=utf-8"
                    ext = "txt"

                object_name = f"exports/{export_type}/{export_id}.{ext}"
                ref = ObjectRef(
                    bucket=settings.minio_bucket_exports, object_name=object_name
                )

                if isinstance(content, bytes):
                    await storage.put_bytes(ref, content, content_type=content_type)
                else:
                    await storage.put_text(ref, content, content_type=content_type)

                job.download_url = await storage.presign_get(
                    ref,
                    response_headers=_build_download_response_headers(
                        export_type=export_type,
                        target_id=target_uuid,
                        content_type=content_type,
                        file_extension=ext,
                    ),
                )
                job.status = ExportStatus.SUCCEEDED
            except AppError as exc:
                job.status = ExportStatus.FAILED
                job.error_code = exc.code
                job.error_message = exc.message
                if exc.details:
                    job.error_message = (
                        f"{exc.message} | {json.dumps(exc.details, ensure_ascii=False)}"
                    )
            except Exception as exc:  # pragma: no cover
                job.status = ExportStatus.FAILED
                job.error_message = str(exc)
            finally:
                await session.commit()

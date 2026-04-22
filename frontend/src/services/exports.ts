/**
 * 导出 API 封装
 */

import {
  DEFAULT_EXPORT_POLL_INTERVAL_MS,
  DEFAULT_EXPORT_POLL_MAX_ATTEMPTS,
} from '../constants/runtimeDefaults';
import { apiFetch, apiV1Path, buildApiRequestUrl } from './http';

export type ExportType = 'chat' | 'research';
export type ExportStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export interface ExportCreateRequest {
  type: ExportType;
  run_id?: string;
  session_id?: string;
}

export interface ExportJob {
  id: string;
  run_id?: string;
  session_id?: string;
  status: ExportStatus;
  download_url: string | null;
  error_code?: string | null;
  error_message: string | null;
  created_at: string;
}

/**
 * 创建导出任务
 */
export async function createExport(data: ExportCreateRequest): Promise<ExportJob> {
  return apiFetch<ExportJob>(apiV1Path('/exports'), {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 获取导出任务状态
 */
export async function getExport(exportId: string): Promise<ExportJob> {
  return apiFetch<ExportJob>(apiV1Path(`/exports/${exportId}`));
}

/**
 * 轮询导出任务直到完成
 */
export async function pollExportUntilDone(
  exportId: string,
  intervalMs = DEFAULT_EXPORT_POLL_INTERVAL_MS,
  maxAttempts = DEFAULT_EXPORT_POLL_MAX_ATTEMPTS
): Promise<ExportJob> {
  for (let i = 0; i < maxAttempts; i++) {
    const job = await getExport(exportId);
    if (job.status === 'succeeded' || job.status === 'failed') {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error('导出任务超时');
}

/**
 * 解析导出下载地址。
 *
 * 后端返回相对路径时，必须绑定到真实后端 API base，
 * 否则前后端分域部署下会误落到前端站点并返回 404。
 */
export function resolveExportDownloadUrl(downloadUrl: string): string {
  const normalized = downloadUrl.trim();
  if (!normalized) {
    return normalized;
  }
  if (/^https?:\/\//i.test(normalized)) {
    return normalized;
  }
  if (normalized.startsWith('/')) {
    return buildApiRequestUrl(normalized);
  }
  return normalized;
}

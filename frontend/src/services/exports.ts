/**
 * 导出 API 封装
 */

import { apiFetch } from './http';

export type ExportType = 'chat' | 'research' | 'evaluation';
export type ExportStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export interface ExportCreateRequest {
  type: ExportType;
  run_id: string;
}

export interface ExportJob {
  id: string;
  run_id?: string;
  status: ExportStatus;
  download_url: string | null;
  error_message: string | null;
  created_at: string;
}

/**
 * 创建导出任务
 */
export async function createExport(data: ExportCreateRequest): Promise<ExportJob> {
  return apiFetch<ExportJob>('/api/v1/exports', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 获取导出任务状态
 */
export async function getExport(exportId: string): Promise<ExportJob> {
  return apiFetch<ExportJob>(`/api/v1/exports/${exportId}`);
}

/**
 * 轮询导出任务直到完成
 */
export async function pollExportUntilDone(
  exportId: string,
  intervalMs = 1000,
  maxAttempts = 60
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

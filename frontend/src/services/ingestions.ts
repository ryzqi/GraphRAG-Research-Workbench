/**
 * 导入任务 API 封装
 */

import { apiFetch } from './http';

export type IngestionStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled';
export type IngestionMode = 'create' | 'update';

export interface IngestionJob {
  id: string;
  kb_id: string;
  status: IngestionStatus;
  error_message: string | null;
  stats: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface IngestionJobCreateRequest {
  kb_id: string;
  material_ids: string[];
  mode?: IngestionMode;
}

/**
 * 创建导入任务
 */
export async function createIngestionJob(
  data: IngestionJobCreateRequest
): Promise<IngestionJob> {
  return apiFetch<IngestionJob>('/api/v1/ingestions', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 获取导入任务状态
 */
export async function getIngestionJob(ingestionId: string): Promise<IngestionJob> {
  return apiFetch<IngestionJob>(`/api/v1/ingestions/${ingestionId}`);
}

/**
 * 取消导入任务
 */
export async function cancelIngestionJob(ingestionId: string): Promise<IngestionJob> {
  return apiFetch<IngestionJob>(`/api/v1/ingestions/${ingestionId}/cancel`, {
    method: 'POST',
  });
}

/**
 * 轮询导入任务状态直到完成
 */
export async function pollIngestionJob(
  ingestionId: string,
  options?: { intervalMs?: number; maxAttempts?: number }
): Promise<IngestionJob> {
  const { intervalMs = 2000, maxAttempts = 60 } = options ?? {};
  let attempts = 0;

  while (attempts < maxAttempts) {
    const job = await getIngestionJob(ingestionId);
    if (['succeeded', 'failed', 'canceled'].includes(job.status)) {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    attempts++;
  }

  throw new Error('导入任务轮询超时');
}

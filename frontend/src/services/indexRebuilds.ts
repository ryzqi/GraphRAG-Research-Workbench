/**
 * 索引重建任务 API 封装
 */
import { apiFetch, apiV1Path } from './http';

export type IndexRebuildStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled';

export interface IndexRebuildJob {
  id: string;
  kb_id: string;
  status: IndexRebuildStatus;
  error_message: string | null;
  stats: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/**
 * 获取索引重建任务状态
 */
export async function getIndexRebuildJob(jobId: string): Promise<IndexRebuildJob> {
  return apiFetch<IndexRebuildJob>(apiV1Path(`/index-rebuilds/${jobId}`));
}

/**
 * 索引重建任务 React Query Hooks
 */
import { useQuery } from '@tanstack/react-query';
import { getIndexRebuildJob, type IndexRebuildJob } from '../../services/indexRebuilds';

const NO_ID = '__none__';

export const indexRebuildKeys = {
  all: ['indexRebuilds'] as const,
  job: (id: string | undefined) => [...indexRebuildKeys.all, 'job', id ?? NO_ID] as const,
};

/**
 * 获取索引重建任务状态（运行中自动轮询）
 */
export function useIndexRebuildJob(jobId: string | undefined) {
  return useQuery<IndexRebuildJob>({
    queryKey: indexRebuildKeys.job(jobId),
    queryFn: () => getIndexRebuildJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 2000 : false;
    },
  });
}

/**
 * 导入任务 React Query Hooks
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  cancelIngestionJob,
  createIngestionJob,
  getIngestionJob,
  type IngestionJobCreateRequest,
} from '../../services/ingestions';

// Query Keys
const NO_ID = '__none__';

const KEYS = {
  all: ['ingestions'] as const,
  job: (id: string | undefined) => [...KEYS.all, 'job', id ?? NO_ID] as const,
};

/**
 * 获取导入任务状态（运行中自动轮询）
 */
export function useIngestionJob(ingestionId: string | undefined) {
  return useQuery({
    queryKey: KEYS.job(ingestionId),
    queryFn: () => getIngestionJob(ingestionId as string),
    enabled: !!ingestionId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 2000 : false;
    },
  });
}

/**
 * 创建导入任务
 */
export function useCreateIngestionJob() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: IngestionJobCreateRequest) => createIngestionJob(data),
    onSuccess: (job) => {
      // 写入缓存，避免创建成功后立刻重复请求。
      queryClient.setQueryData(KEYS.job(job.id), job);
    },
  });
}

/**
 * 取消导入任务
 */
export function useCancelIngestionJob() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (ingestionId: string) => cancelIngestionJob(ingestionId),
    onSuccess: (job) => {
      queryClient.setQueryData(KEYS.job(job.id), job);
    },
  });
}

export { KEYS as ingestionKeys };

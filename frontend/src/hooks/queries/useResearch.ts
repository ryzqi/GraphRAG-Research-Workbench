/**
 * 研究相关 React Query Hooks
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  createResearchRun,
  getResearchRun,
  getResearchReport,
  cancelResearchRun,
  type ResearchRunCreateRequest,
} from '../../services/research';

// Query Keys
const KEYS = {
  all: ['research'] as const,
  runs: () => [...KEYS.all, 'runs'] as const,
  run: (id: string) => [...KEYS.all, 'run', id] as const,
  report: (runId: string) => [...KEYS.all, 'report', runId] as const,
};

/**
 * 获取研究状态
 */
export function useResearchRun(runId: string | undefined) {
  return useQuery({
    queryKey: KEYS.run(runId!),
    queryFn: () => getResearchRun(runId!),
    enabled: !!runId,
    refetchInterval: (query) => {
      // 仅在运行中时自动轮询
      const status = query.state.data?.status;
      return status === 'running' ? 2000 : false;
    },
  });
}

/**
 * 获取研究报告
 */
export function useResearchReport(runId: string | undefined) {
  return useQuery({
    queryKey: KEYS.report(runId!),
    queryFn: () => getResearchReport(runId!),
    enabled: !!runId,
  });
}

/**
 * 发起深度研究
 */
export function useCreateResearchRun() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ResearchRunCreateRequest) => createResearchRun(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.runs() });
    },
  });
}

/**
 * 取消研究任务
 */
export function useCancelResearchRun() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (runId: string) => cancelResearchRun(runId),
    onSuccess: (_, runId) => {
      queryClient.invalidateQueries({ queryKey: KEYS.run(runId) });
    },
  });
}

export { KEYS as researchKeys };

/**
 * 评测相关 React Query Hooks
 */
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  createEvaluationRun,
  getEvaluationRun,
  type EvaluationRunCreateRequest,
} from '../../services/evaluations';

// Query Keys
const KEYS = {
  all: ['evaluations'] as const,
  run: (id: string) => [...KEYS.all, 'run', id] as const,
};

/**
 * 获取评测任务状态（运行中自动轮询）
 */
export function useEvaluationRun(evalRunId: string | undefined) {
  return useQuery({
    queryKey: KEYS.run(evalRunId!),
    queryFn: () => getEvaluationRun(evalRunId!),
    enabled: !!evalRunId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 3000 : false;
    },
  });
}

/**
 * 发起评测任务
 */
export function useCreateEvaluationRun() {
  return useMutation({
    mutationFn: (data: EvaluationRunCreateRequest) => createEvaluationRun(data),
  });
}

export { KEYS as evaluationKeys };

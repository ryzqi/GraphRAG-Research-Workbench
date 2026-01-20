/**
 * 评测相关 React Query Hooks
 */
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { parseSseJson } from '../../lib/sse';
import {
  createEvaluationRun,
  getEvaluationRun,
  streamEvaluationRun,
  type EvaluationRunCreateRequest,
} from '../../services/evaluations';

// Query Keys
const NO_ID = '__none__';

const KEYS = {
  all: ['evaluations'] as const,
  run: (id: string | undefined) => [...KEYS.all, 'run', id ?? NO_ID] as const,
};

/**
 * 获取评测任务状态（运行中自动轮询）
 */
export function useEvaluationRun(evalRunId: string | undefined) {
  const queryClient = useQueryClient();
  const [streamStatus, setStreamStatus] = useState<'idle' | 'active' | 'failed'>('idle');

  useEffect(() => {
    if (!evalRunId) return;

    const controller = new AbortController();
    let active = true;

    (async () => {
      try {
        const stream = await streamEvaluationRun(evalRunId, controller.signal);
        setStreamStatus('active');
        for await (const event of stream) {
          if (!active) break;
          if (event.event === 'update' || event.event === 'final') {
            const data = parseSseJson(event.data);
            queryClient.setQueryData(KEYS.run(evalRunId), data);
            if (event.event === 'final') {
              setStreamStatus('idle');
              break;
            }
          }
          if (event.event === 'error') {
            throw new Error('评测进度流异常');
          }
        }
      } catch (e) {
        if (!active || controller.signal.aborted) return;
        setStreamStatus('failed');
      }
    })();

    return () => {
      active = false;
      controller.abort();
    };
  }, [evalRunId, queryClient]);

  return useQuery({
    queryKey: KEYS.run(evalRunId),
    queryFn: () => getEvaluationRun(evalRunId as string),
    enabled: !!evalRunId,
    refetchInterval: (query) => {
      if (streamStatus === 'active') return false;
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

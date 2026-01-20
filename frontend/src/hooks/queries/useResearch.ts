/**
 * 研究相关 React Query Hooks
 */
import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { parseSseJson } from '../../lib/sse';
import {
  createResearchRun,
  getResearchRun,
  getResearchReport,
  cancelResearchRun,
  streamResearchRun,
  type ResearchRunCreateRequest,
} from '../../services/research';

// Query Keys
const NO_ID = '__none__';

const KEYS = {
  all: ['research'] as const,
  runs: () => [...KEYS.all, 'runs'] as const,
  run: (id: string | undefined) => [...KEYS.all, 'run', id ?? NO_ID] as const,
  report: (runId: string | undefined) => [...KEYS.all, 'report', runId ?? NO_ID] as const,
};

/**
 * 获取研究状态
 */
export function useResearchRun(runId: string | undefined) {
  const queryClient = useQueryClient();
  const [streamStatus, setStreamStatus] = useState<'idle' | 'active' | 'failed'>('idle');

  useEffect(() => {
    if (!runId) return;

    const controller = new AbortController();
    let active = true;

    (async () => {
      try {
        const stream = await streamResearchRun(runId, controller.signal);
        setStreamStatus('active');
        for await (const event of stream) {
          if (!active) break;
          if (event.event === 'update' || event.event === 'final') {
            const data = parseSseJson(event.data);
            queryClient.setQueryData(KEYS.run(runId), data);
            if (event.event === 'final') {
              setStreamStatus('idle');
              break;
            }
          }
          if (event.event === 'error') {
            throw new Error('研究进度流异常');
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
  }, [runId, queryClient]);

  return useQuery({
    queryKey: KEYS.run(runId),
    queryFn: () => getResearchRun(runId as string),
    enabled: !!runId,
    refetchInterval: (query) => {
      if (streamStatus === 'active') return false;
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
    queryKey: KEYS.report(runId),
    queryFn: () => getResearchReport(runId as string),
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

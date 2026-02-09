/**
 * Evaluation hooks based on SWR
 */
import { useEffect, useState } from 'react';
import { useSWRConfig } from 'swr';
import { parseSseJson } from '../../lib/sse';
import { useApiMutation, useApiQuery } from '../../lib/swr';
import {
  createEvaluationRun,
  getEvaluationRun,
  streamEvaluationRun,
  type EvaluationRun,
  type EvaluationRunCreateRequest,
} from '../../services/evaluations';

const NO_ID = '__none__';
const STREAM_MUTATION_INTERVAL_MS = 250;

const KEYS = {
  all: ['evaluations'] as const,
  run: (id: string | undefined) => [...KEYS.all, 'run', id ?? NO_ID] as const,
};

export function useEvaluationRun(evalRunId: string | undefined) {
  const { mutate } = useSWRConfig();
  const [streamStatus, setStreamStatus] = useState<'idle' | 'active' | 'failed'>('idle');

  useEffect(() => {
    if (!evalRunId) {
      setStreamStatus('idle');
      return;
    }

    const controller = new AbortController();
    let active = true;
    let pendingRun: EvaluationRun | null = null;
    let flushTimer: ReturnType<typeof setTimeout> | null = null;

    const flushPendingRun = async () => {
      if (!pendingRun || !active) {
        return;
      }
      const snapshot = pendingRun;
      pendingRun = null;
      await mutate(KEYS.run(evalRunId), snapshot, { revalidate: false });
    };

    const scheduleFlush = () => {
      if (flushTimer !== null) {
        return;
      }
      flushTimer = setTimeout(() => {
        flushTimer = null;
        void flushPendingRun();
      }, STREAM_MUTATION_INTERVAL_MS);
    };

    void (async () => {
      try {
        const stream = await streamEvaluationRun(evalRunId, controller.signal);
        setStreamStatus('active');

        for await (const event of stream) {
          if (!active) break;

          if (event.event === 'update' || event.event === 'final') {
            pendingRun = parseSseJson<EvaluationRun>(event.data);

            if (event.event === 'final') {
              if (flushTimer !== null) {
                clearTimeout(flushTimer);
                flushTimer = null;
              }
              await flushPendingRun();
              setStreamStatus('idle');
              break;
            }

            scheduleFlush();
          }

          if (event.event === 'error') {
            throw new Error('Evaluation progress stream failed');
          }
        }
      } catch {
        if (!active || controller.signal.aborted) {
          return;
        }
        setStreamStatus('failed');
      }
    })();

    return () => {
      active = false;
      if (flushTimer !== null) {
        clearTimeout(flushTimer);
      }
      controller.abort();
    };
  }, [evalRunId, mutate]);

  return useApiQuery<EvaluationRun>(
    evalRunId ? KEYS.run(evalRunId) : null,
    evalRunId ? () => getEvaluationRun(evalRunId) : null,
    {
      refreshInterval: (latestRun) => {
        if (streamStatus === 'active') {
          return 0;
        }
        const status = (latestRun as EvaluationRun | undefined)?.status;
        return status === 'queued' || status === 'running' ? 3_000 : 0;
      },
    }
  );
}

export function useCreateEvaluationRun() {
  return useApiMutation((data: EvaluationRunCreateRequest) => createEvaluationRun(data));
}

export { KEYS as evaluationKeys };

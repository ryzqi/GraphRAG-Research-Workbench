/**
 * Research hooks based on SWR
 */
import { useEffect, useState } from 'react';
import { useSWRConfig } from 'swr';
import { parseSseJson } from '../../lib/sse';
import { useApiMutation, useApiQuery } from '../../lib/swr';
import type { AgentRun } from '../../services/chats';
import {
  createResearchRun,
  getResearchRun,
  getResearchReport,
  cancelResearchRun,
  streamResearchRun,
  type ResearchReport,
  type ResearchRunCreateRequest,
} from '../../services/research';

const NO_ID = '__none__';
const STREAM_MUTATION_INTERVAL_MS = 250;

const KEYS = {
  all: ['research'] as const,
  runs: () => [...KEYS.all, 'runs'] as const,
  run: (id: string | undefined) => [...KEYS.all, 'run', id ?? NO_ID] as const,
  report: (runId: string | undefined) => [...KEYS.all, 'report', runId ?? NO_ID] as const,
};

export function useResearchRun(runId: string | undefined) {
  const { mutate } = useSWRConfig();
  const [streamStatus, setStreamStatus] = useState<'idle' | 'active' | 'failed'>('idle');

  useEffect(() => {
    if (!runId) {
      setStreamStatus('idle');
      return;
    }

    const controller = new AbortController();
    let active = true;
    let pendingRun: AgentRun | null = null;
    let flushTimer: ReturnType<typeof setTimeout> | null = null;

    const flushPendingRun = async () => {
      if (!pendingRun || !active) {
        return;
      }
      const snapshot = pendingRun;
      pendingRun = null;
      await mutate(KEYS.run(runId), snapshot, { revalidate: false });
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
        const stream = await streamResearchRun(runId, controller.signal);
        setStreamStatus('active');

        for await (const event of stream) {
          if (!active) break;

          if (event.event === 'update' || event.event === 'final') {
            pendingRun = parseSseJson<AgentRun>(event.data);

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
            throw new Error('Research progress stream failed');
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
  }, [runId, mutate]);

  return useApiQuery<AgentRun>(
    runId ? KEYS.run(runId) : null,
    runId ? () => getResearchRun(runId) : null,
    {
      refreshInterval: (latestRun) => {
        if (streamStatus === 'active') {
          return 0;
        }
        return (latestRun as AgentRun | undefined)?.status === 'running' ? 2_000 : 0;
      },
    }
  );
}

export function useResearchReport(runId: string | undefined) {
  return useApiQuery<ResearchReport>(
    runId ? KEYS.report(runId) : null,
    runId ? () => getResearchReport(runId) : null
  );
}

export function useCreateResearchRun() {
  return useApiMutation((data: ResearchRunCreateRequest) => createResearchRun(data), {
    onSuccess: async (_, __, { invalidate }) => {
      await invalidate([KEYS.runs()]);
    },
  });
}

export function useCancelResearchRun() {
  return useApiMutation((runId: string) => cancelResearchRun(runId), {
    onSuccess: async (_, runId, { invalidate }) => {
      await invalidate([KEYS.run(runId), KEYS.runs()]);
    },
  });
}

export { KEYS as researchKeys };

/**
 * Ingestion batch hooks based on SWR
 */
import { useEffect, useMemo, useState } from 'react';
import { useSWRConfig } from 'swr';
import { parseSseJson } from '../../lib/sse';
import {
  cancelIngestionBatch,
  createIngestionBatch,
  getIngestionBatch,
  getLatestIngestionBatch,
  retryIngestionBatch,
  streamIngestionBatch,
  type IngestionBatchCreateRequest,
  type IngestionBatch,
} from '../../services/ingestionBatches';
import { useApiMutation, useApiQuery } from '../../lib/swr';

const NO_ID = '__none__';
const DEFAULT_POLLING_INTERVAL_MS = 2_000;
const FALLBACK_POLLING_STEPS = [1_000, 2_000, 5_000] as const;
const STREAM_RETRY_MULTIPLIER = 2;

type StreamStatus = 'idle' | 'connecting' | 'live' | 'fallback_polling';

interface UseIngestionBatchOptions {
  refreshIntervalMs?: number;
}

interface UseIngestionBatchLiveOptions {
  kbId?: string;
  batchId?: string;
}

interface UseIngestionBatchLiveResult {
  data: IngestionBatch | undefined;
  error: Error | undefined;
  isPending: boolean;
  isFetching: boolean;
  refetch: () => Promise<IngestionBatch | undefined>;
  resolvedBatchId: string | undefined;
  streamStatus: StreamStatus;
  fallbackIntervalMs: number;
}

interface UseCreateIngestionBatchOptions {
  invalidateMode?: 'blocking' | 'background';
}

const KEYS = {
  all: ['ingestionBatches'] as const,
  batch: (id: string | undefined) => [...KEYS.all, 'batch', id ?? NO_ID] as const,
  latest: (kbId: string) => [...KEYS.all, 'latest', kbId || NO_ID] as const,
};

function isBatchRunning(batch: IngestionBatch | undefined): boolean {
  if (!batch) {
    return false;
  }
  return batch.status === 'processing';
}

function isBatchTerminal(batch: IngestionBatch | undefined): boolean {
  if (!batch) {
    return false;
  }
  return batch.status === 'completed';
}

function matchesArrayKeyPrefix(cachedKey: unknown, prefixKey: readonly unknown[]): boolean {
  if (!Array.isArray(cachedKey) || cachedKey.length < prefixKey.length) {
    return false;
  }

  return prefixKey.every((segment, index) => Object.is(cachedKey[index], segment));
}

export function useIngestionBatch(batchId: string | undefined, options?: UseIngestionBatchOptions) {
  const refreshIntervalMs = options?.refreshIntervalMs ?? DEFAULT_POLLING_INTERVAL_MS;
  return useApiQuery(
    batchId ? KEYS.batch(batchId) : null,
    batchId ? () => getIngestionBatch(batchId) : null,
    {
      refreshInterval: (latestBatch) =>
        isBatchRunning(latestBatch as IngestionBatch | undefined) ? refreshIntervalMs : 0,
    }
  );
}

export function useIngestionBatchLive(options: UseIngestionBatchLiveOptions): UseIngestionBatchLiveResult {
  const { mutate } = useSWRConfig();
  const [streamStatus, setStreamStatus] = useState<StreamStatus>('idle');
  const [fallbackStep, setFallbackStep] = useState(0);
  const [streamRevision, setStreamRevision] = useState(0);

  const kbId = options.kbId;
  const preferredBatchId = options.batchId;

  const latestBatchQuery = useApiQuery(
    kbId ? KEYS.latest(kbId) : null,
    kbId ? () => getLatestIngestionBatch(kbId) : null
  );

  const resolvedBatchId = preferredBatchId ?? latestBatchQuery.data?.id;

  const fallbackIntervalMs =
    streamStatus === 'fallback_polling'
      ? FALLBACK_POLLING_STEPS[Math.min(fallbackStep, FALLBACK_POLLING_STEPS.length - 1)]
      : 0;

  const pollingIntervalMs =
    streamStatus === 'live' || streamStatus === 'connecting'
      ? 0
      : streamStatus === 'fallback_polling'
        ? fallbackIntervalMs
        : DEFAULT_POLLING_INTERVAL_MS;

  const batchQuery = useIngestionBatch(resolvedBatchId, {
    refreshIntervalMs: pollingIntervalMs,
  });

  const shouldStream = useMemo(() => {
    if (!resolvedBatchId) {
      return false;
    }
    if (isBatchTerminal(batchQuery.data)) {
      return false;
    }
    return true;
  }, [resolvedBatchId, batchQuery.data]);

  useEffect(() => {
    setStreamStatus('idle');
    setFallbackStep(0);
    setStreamRevision(0);
  }, [resolvedBatchId]);

  useEffect(() => {
    if (!shouldStream || !resolvedBatchId) {
      setStreamStatus('idle');
      return;
    }

    const controller = new AbortController();
    let active = true;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const scheduleRetry = () => {
      let nextStep = 0;
      setFallbackStep((prev) => {
        nextStep = Math.min(prev + 1, FALLBACK_POLLING_STEPS.length - 1);
        return nextStep;
      });
      setStreamStatus('fallback_polling');

      const retryDelayMs = FALLBACK_POLLING_STEPS[nextStep] * STREAM_RETRY_MULTIPLIER;
      retryTimer = setTimeout(() => {
        if (!active) {
          return;
        }
        setStreamRevision((prev) => prev + 1);
      }, retryDelayMs);
    };

    void (async () => {
      try {
        setStreamStatus('connecting');
        const stream = await streamIngestionBatch(resolvedBatchId, controller.signal);
        if (!active) {
          return;
        }

        setStreamStatus('live');
        setFallbackStep(0);

        for await (const event of stream) {
          if (!active) {
            break;
          }

          if (event.event === 'meta' || event.event === 'heartbeat') {
            continue;
          }

          if (event.event === 'snapshot' || event.event === 'update' || event.event === 'final') {
            const payload = parseSseJson<IngestionBatch>(event.data);
            await mutate(KEYS.batch(resolvedBatchId), payload, { revalidate: false });

            if (event.event === 'final') {
              setStreamStatus('idle');
              await Promise.all([
                mutate(KEYS.batch(resolvedBatchId)),
                mutate((cachedKey) => matchesArrayKeyPrefix(cachedKey, ['knowledgeBases']), undefined, {
                  revalidate: true,
                }),
                mutate((cachedKey) => matchesArrayKeyPrefix(cachedKey, ['materials']), undefined, {
                  revalidate: true,
                }),
                mutate((cachedKey) => matchesArrayKeyPrefix(cachedKey, ['materialChunks']), undefined, {
                  revalidate: true,
                }),
              ]);
              return;
            }

            continue;
          }

          if (event.event === 'error') {
            throw new Error('Ingestion status stream failed');
          }
        }
      } catch {
        if (!active || controller.signal.aborted) {
          return;
        }
        scheduleRetry();
      }
    })();

    return () => {
      active = false;
      controller.abort();
      if (retryTimer !== null) {
        clearTimeout(retryTimer);
      }
    };
  }, [shouldStream, resolvedBatchId, streamRevision, mutate]);

  const error = batchQuery.error ?? latestBatchQuery.error;

  return {
    data: batchQuery.data ?? (preferredBatchId ? undefined : latestBatchQuery.data ?? undefined),
    error,
    isPending: (resolvedBatchId ? batchQuery.isPending : latestBatchQuery.isPending) || false,
    isFetching: Boolean(batchQuery.isFetching || latestBatchQuery.isFetching),
    refetch: async () => {
      if (kbId) {
        await latestBatchQuery.refetch();
      }
      return batchQuery.refetch();
    },
    resolvedBatchId,
    streamStatus,
    fallbackIntervalMs,
  };
}

export function useCreateIngestionBatch(options?: UseCreateIngestionBatchOptions) {
  const invalidateMode = options?.invalidateMode ?? 'background';

  return useApiMutation((data: IngestionBatchCreateRequest) => createIngestionBatch(data), {
    onSuccess: async (resp, __, { invalidate }) => {
      const keysToInvalidate: Array<readonly unknown[]> = [
        KEYS.all,
        ['knowledgeBases'],
        ['materials'],
        ['materialChunks'],
        ['research'],
        ['evaluations'],
        ['chats'],
      ];
      if (resp.batch_id) {
        keysToInvalidate.push(KEYS.batch(resp.batch_id));
      }
      if (resp.kb_id) {
        keysToInvalidate.push(KEYS.latest(resp.kb_id));
      }

      const invalidatePromise = invalidate(keysToInvalidate);
      if (invalidateMode === 'blocking') {
        await invalidatePromise;
        return;
      }
      void invalidatePromise;
    },
  });
}

export function useRetryIngestionBatch() {
  return useApiMutation((batchId: string) => retryIngestionBatch(batchId), {
    onSuccess: async (_, batchId, { invalidate }) => {
      await invalidate([KEYS.batch(batchId), KEYS.all, ['materialChunks']]);
    },
  });
}

export function useCancelIngestionBatch() {
  return useApiMutation((batchId: string) => cancelIngestionBatch(batchId), {
    onSuccess: async (_, batchId, { invalidate }) => {
      await invalidate([KEYS.batch(batchId), KEYS.all, ['materialChunks']]);
    },
  });
}

export { KEYS as ingestionBatchKeys };

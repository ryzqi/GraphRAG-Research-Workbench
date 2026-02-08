/**
 * Ingestion batch hooks based on SWR
 */
import {
  cancelIngestionBatch,
  createIngestionBatch,
  getIngestionBatch,
  retryIngestionBatch,
  type IngestionBatchCreateRequest,
  type IngestionBatch,
} from '../../services/ingestionBatches';
import { useApiMutation, useApiQuery } from '../../lib/swr';

const NO_ID = '__none__';

const KEYS = {
  all: ['ingestionBatches'] as const,
  batch: (id: string | undefined) => [...KEYS.all, 'batch', id ?? NO_ID] as const,
};

function isBatchRunning(batch: IngestionBatch | undefined): boolean {
  if (!batch) {
    return false;
  }
  return batch.status === 'queued' || batch.status === 'running';
}

export function useIngestionBatch(batchId: string | undefined) {
  return useApiQuery(
    batchId ? KEYS.batch(batchId) : null,
    batchId ? () => getIngestionBatch(batchId) : null,
    {
      refreshInterval: (latestBatch) =>
        isBatchRunning(latestBatch as IngestionBatch | undefined) ? 2_000 : 0,
    }
  );
}

export function useCreateIngestionBatch() {
  return useApiMutation((data: IngestionBatchCreateRequest) => createIngestionBatch(data), {
    onSuccess: async (resp, __, { invalidate }) => {
      const keysToInvalidate: Array<readonly unknown[]> = [
        KEYS.all,
        ['knowledgeBases'],
        ['materials'],
        ['research'],
        ['evaluations'],
        ['chats'],
      ];
      if (resp.batch_id) {
        keysToInvalidate.push(KEYS.batch(resp.batch_id));
      }
      await invalidate(keysToInvalidate);
    },
  });
}

export function useRetryIngestionBatch() {
  return useApiMutation((batchId: string) => retryIngestionBatch(batchId), {
    onSuccess: async (_, batchId, { invalidate }) => {
      await invalidate([KEYS.batch(batchId), KEYS.all]);
    },
  });
}

export function useCancelIngestionBatch() {
  return useApiMutation((batchId: string) => cancelIngestionBatch(batchId), {
    onSuccess: async (_, batchId, { invalidate }) => {
      await invalidate([KEYS.batch(batchId), KEYS.all]);
    },
  });
}

export { KEYS as ingestionBatchKeys };


/**
 * ingestion-batch React Query Hooks
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  cancelIngestionBatch,
  createIngestionBatch,
  getIngestionBatch,
  retryIngestionBatch,
  type IngestionBatchCreateRequest,
  type IngestionBatch,
} from '../../services/ingestionBatches';

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
  return useQuery({
    queryKey: KEYS.batch(batchId),
    queryFn: () => getIngestionBatch(batchId as string),
    enabled: !!batchId,
    refetchInterval: (query) => (isBatchRunning(query.state.data) ? 2000 : false),
  });
}

export function useCreateIngestionBatch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: IngestionBatchCreateRequest) => createIngestionBatch(data),
    onSuccess: (resp) => {
      queryClient.invalidateQueries({ queryKey: KEYS.all });
      queryClient.invalidateQueries({ queryKey: ['knowledgeBases'] });
      queryClient.invalidateQueries({ queryKey: ['materials'] });
      queryClient.invalidateQueries({ queryKey: ['research'] });
      queryClient.invalidateQueries({ queryKey: ['evaluations'] });
      queryClient.invalidateQueries({ queryKey: ['chats'] });
      if (resp.batch_id) {
        queryClient.invalidateQueries({ queryKey: KEYS.batch(resp.batch_id) });
      }
    },
  });
}

export function useRetryIngestionBatch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (batchId: string) => retryIngestionBatch(batchId),
    onSuccess: (_, batchId) => {
      queryClient.invalidateQueries({ queryKey: KEYS.batch(batchId) });
      queryClient.invalidateQueries({ queryKey: KEYS.all });
    },
  });
}

export function useCancelIngestionBatch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (batchId: string) => cancelIngestionBatch(batchId),
    onSuccess: (_, batchId) => {
      queryClient.invalidateQueries({ queryKey: KEYS.batch(batchId) });
      queryClient.invalidateQueries({ queryKey: KEYS.all });
    },
  });
}

export { KEYS as ingestionBatchKeys };

/**
 * Knowledge base hooks based on SWR
 */
import {
  listKnowledgeBases,
  listSelectableKnowledgeBases,
  getKnowledgeBase,
  getKnowledgeBaseIngestionState,
  createKnowledgeBase,
  updateKnowledgeBase,
  deleteKnowledgeBase,
  archiveKnowledgeBase,
  updateKnowledgeBaseIndexConfig,
  type KnowledgeBaseCreate,
  type KnowledgeBaseUpdate,
  type IndexConfig,
  type KnowledgeBaseIndexConfigUpdateResponse,
  type KnowledgeBaseStatusFilter,
  type KnowledgeBaseReadinessFilter,
  type KnowledgeBaseIngestionState,
} from '../../services/knowledgeBases';
import { useApiMutation, useApiQuery } from '../../lib/swr';
import { indexRebuildKeys } from './useIndexRebuilds';

const KEYS = {
  all: ['knowledgeBases'] as const,
  list: (status: KnowledgeBaseStatusFilter, readiness: KnowledgeBaseReadinessFilter) =>
    [...KEYS.all, 'list', status, readiness] as const,
  selectable: () => [...KEYS.all, 'selectable'] as const,
  detail: (id: string) => [...KEYS.all, 'detail', id] as const,
  ingestionState: (id: string) => [...KEYS.all, 'ingestionState', id] as const,
};

export function useKnowledgeBases(params?: {
  status?: KnowledgeBaseStatusFilter;
  readiness?: KnowledgeBaseReadinessFilter;
}) {
  const status = params?.status ?? 'active';
  const readiness = params?.readiness ?? 'all';

  return useApiQuery(
    KEYS.list(status, readiness),
    () => listKnowledgeBases({ status, readiness }).then((res) => res.items)
  );
}

export function useSelectableKnowledgeBases() {
  return useApiQuery(KEYS.selectable(), () =>
    listSelectableKnowledgeBases().then((res) => res.items)
  );
}

export function useKnowledgeBase(id: string) {
  return useApiQuery(
    id ? KEYS.detail(id) : null,
    id ? () => getKnowledgeBase(id) : null
  );
}

export function useKnowledgeBaseIngestionState(id: string) {
  return useApiQuery(
    id ? KEYS.ingestionState(id) : null,
    id ? () => getKnowledgeBaseIngestionState(id) : null,
    {
      refreshInterval: (latestState) =>
        (latestState as KnowledgeBaseIngestionState | undefined)?.has_active_batch
          ? 2_000
          : 0,
    }
  );
}

export function useCreateKnowledgeBase() {
  return useApiMutation((data: KnowledgeBaseCreate) => createKnowledgeBase(data), {
    onSuccess: async (_, __, { invalidate }) => {
      await invalidate([KEYS.all, KEYS.selectable()]);
    },
  });
}

export function useUpdateKnowledgeBase() {
  return useApiMutation(
    ({ id, data }: { id: string; data: KnowledgeBaseUpdate }) =>
      updateKnowledgeBase(id, data),
    {
      onSuccess: async (_, { id }, { invalidate }) => {
        await invalidate([KEYS.all, KEYS.detail(id), KEYS.selectable()]);
      },
    }
  );
}

export function useUpdateKnowledgeBaseIndexConfig() {
  return useApiMutation(
    ({ id, index_config }: { id: string; index_config: IndexConfig }) =>
      updateKnowledgeBaseIndexConfig(id, index_config),
    {
      onSuccess: async (
        res: KnowledgeBaseIndexConfigUpdateResponse,
        { id },
        { invalidate, setCachedData }
      ) => {
        await invalidate([KEYS.all, KEYS.selectable()]);
        await setCachedData(KEYS.detail(id), res.knowledge_base);
        if (res.rebuild_job) {
          await setCachedData(indexRebuildKeys.job(res.rebuild_job.id), res.rebuild_job);
        }
      },
    }
  );
}

export function useDeleteKnowledgeBase() {
  return useApiMutation((id: string) => deleteKnowledgeBase(id), {
    onSuccess: async (_, id, { invalidate }) => {
      await invalidate([KEYS.all, KEYS.detail(id), KEYS.selectable()]);
    },
  });
}

export function useArchiveKnowledgeBase() {
  return useApiMutation((id: string) => archiveKnowledgeBase(id), {
    onSuccess: async (_, id, { invalidate }) => {
      await invalidate([KEYS.all, KEYS.detail(id), KEYS.selectable()]);
    },
  });
}

export { KEYS as knowledgeBaseKeys };

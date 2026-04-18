/**
 * Knowledge base hooks based on SWR
 */
import { useSWRConfig } from 'swr';
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
  mergeKnowledgeBaseIntoCollection,
  type KnowledgeBase,
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

interface KnowledgeBaseMutationSuccessDeps {
  invalidate: (keys: Array<readonly unknown[]>) => Promise<void>;
  setCachedData: <TData>(
    key: readonly unknown[],
    data: TData
  ) => Promise<TData | undefined>;
}

interface KnowledgeBaseUpdateSuccessDeps extends KnowledgeBaseMutationSuccessDeps {
  updateSelectableCollection: (updated: KnowledgeBase) => Promise<KnowledgeBase[] | undefined>;
  updateListCollections: (updated: KnowledgeBase) => Promise<unknown>;
}

export async function applyKnowledgeBaseUpdateSuccess(
  updated: KnowledgeBase,
  id: string,
  deps: KnowledgeBaseUpdateSuccessDeps
) {
  await Promise.all([
    deps.setCachedData(KEYS.detail(id), updated),
    deps.updateSelectableCollection(updated),
    deps.updateListCollections(updated),
  ]);
  void deps.invalidate([KEYS.all]);
}

export async function applyKnowledgeBaseIndexConfigSuccess(
  res: KnowledgeBaseIndexConfigUpdateResponse,
  id: string,
  deps: KnowledgeBaseMutationSuccessDeps
) {
  const tasks: Promise<unknown>[] = [
    deps.invalidate([KEYS.all, KEYS.selectable()]),
    deps.setCachedData(KEYS.detail(id), res.knowledge_base),
  ];

  if (res.rebuild_job) {
    tasks.push(
      deps.setCachedData(indexRebuildKeys.job(res.rebuild_job.id), res.rebuild_job)
    );
  }

  await Promise.all(tasks);
}

interface UseCreateKnowledgeBaseOptions {
  invalidateMode?: 'blocking' | 'background';
}

interface UseKnowledgeBaseIngestionStateOptions {
  pausePolling?: boolean;
}

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
  , {
    skipInitialFetchIfCached: true,
  });
}

export function useKnowledgeBase(id: string) {
  return useApiQuery(
    id ? KEYS.detail(id) : null,
    id ? () => getKnowledgeBase(id) : null,
    {
      skipInitialFetchIfCached: true,
    }
  );
}

export function shouldPollKnowledgeBaseIngestionState(
  state: KnowledgeBaseIngestionState | undefined,
  pausePolling: boolean
): boolean {
  if (pausePolling) {
    return false;
  }
  return Boolean(state?.has_active_batch);
}

export function useKnowledgeBaseIngestionState(
  id: string,
  options?: UseKnowledgeBaseIngestionStateOptions
) {
  const pausePolling = options?.pausePolling ?? false;
  return useApiQuery(
    id ? KEYS.ingestionState(id) : null,
    id ? () => getKnowledgeBaseIngestionState(id) : null,
    {
      skipInitialFetchIfCached: true,
      refreshInterval: (latestState) =>
        shouldPollKnowledgeBaseIngestionState(
          latestState as KnowledgeBaseIngestionState | undefined,
          pausePolling
        )
          ? 2_000
          : 0,
    }
  );
}

export function useCreateKnowledgeBase(options?: UseCreateKnowledgeBaseOptions) {
  const invalidateMode = options?.invalidateMode ?? 'blocking';
  return useApiMutation((data: KnowledgeBaseCreate) => createKnowledgeBase(data), {
    onSuccess: async (_, __, { invalidate }) => {
      const invalidatePromise = invalidate([KEYS.all, KEYS.selectable()]);
      if (invalidateMode === 'blocking') {
        await invalidatePromise;
        return;
      }
      void invalidatePromise;
    },
  });
}

export function useUpdateKnowledgeBase() {
  const { mutate } = useSWRConfig();
  return useApiMutation(
    ({ id, data }: { id: string; data: KnowledgeBaseUpdate }) =>
      updateKnowledgeBase(id, data),
    {
      onSuccess: async (updated, { id }, { invalidate, setCachedData }) => {
        await applyKnowledgeBaseUpdateSuccess(updated, id, {
          invalidate,
          setCachedData,
          updateSelectableCollection: async (nextKnowledgeBase) =>
            mutate<KnowledgeBase[] | undefined>(
              KEYS.selectable(),
              (current) => mergeKnowledgeBaseIntoCollection(current, nextKnowledgeBase),
              { revalidate: false, populateCache: true }
            ),
          updateListCollections: async (nextKnowledgeBase) =>
            mutate<KnowledgeBase[] | undefined>(
              (cachedKey) =>
                Array.isArray(cachedKey) &&
                cachedKey.length >= 2 &&
                Object.is(cachedKey[0], KEYS.all[0]) &&
                Object.is(cachedKey[1], 'list'),
              (current) => mergeKnowledgeBaseIntoCollection(current, nextKnowledgeBase),
              { revalidate: false, populateCache: true }
            ),
        });
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
        await applyKnowledgeBaseIndexConfigSuccess(res, id, {
          invalidate,
          setCachedData,
        });
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

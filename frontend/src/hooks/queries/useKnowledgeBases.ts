/**
 * 知识库相关 React Query Hooks
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listKnowledgeBases,
  listSelectableKnowledgeBases,
  getKnowledgeBase,
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
} from '../../services/knowledgeBases';
import { indexRebuildKeys } from './useIndexRebuilds';

const KEYS = {
  all: ['knowledgeBases'] as const,
  list: (status: KnowledgeBaseStatusFilter, readiness: KnowledgeBaseReadinessFilter) =>
    [...KEYS.all, 'list', status, readiness] as const,
  selectable: () => [...KEYS.all, 'selectable'] as const,
  detail: (id: string) => [...KEYS.all, 'detail', id] as const,
};

export function useKnowledgeBases(params?: {
  status?: KnowledgeBaseStatusFilter;
  readiness?: KnowledgeBaseReadinessFilter;
}) {
  const status = params?.status ?? 'active';
  const readiness = params?.readiness ?? 'all';
  return useQuery({
    queryKey: KEYS.list(status, readiness),
    queryFn: () => listKnowledgeBases({ status, readiness }).then((res) => res.items),
  });
}

export function useSelectableKnowledgeBases() {
  return useQuery({
    queryKey: KEYS.selectable(),
    queryFn: () => listSelectableKnowledgeBases().then((res) => res.items),
  });
}

export function useKnowledgeBase(id: string) {
  return useQuery({
    queryKey: KEYS.detail(id),
    queryFn: () => getKnowledgeBase(id),
    enabled: !!id,
  });
}

export function useCreateKnowledgeBase() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: KnowledgeBaseCreate) => createKnowledgeBase(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.all });
    },
  });
}

export function useUpdateKnowledgeBase() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: KnowledgeBaseUpdate }) =>
      updateKnowledgeBase(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: KEYS.all });
      queryClient.invalidateQueries({ queryKey: KEYS.detail(id) });
    },
  });
}

export function useUpdateKnowledgeBaseIndexConfig() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, index_config }: { id: string; index_config: IndexConfig }) =>
      updateKnowledgeBaseIndexConfig(id, index_config),
    onSuccess: (res: KnowledgeBaseIndexConfigUpdateResponse, { id }) => {
      queryClient.invalidateQueries({ queryKey: KEYS.all });
      queryClient.setQueryData(KEYS.detail(id), res.knowledge_base);
      if (res.rebuild_job) {
        queryClient.setQueryData(indexRebuildKeys.job(res.rebuild_job.id), res.rebuild_job);
      }
    },
  });
}

export function useDeleteKnowledgeBase() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => deleteKnowledgeBase(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.all });
    },
  });
}

export function useArchiveKnowledgeBase() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => archiveKnowledgeBase(id),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: KEYS.all });
      queryClient.invalidateQueries({ queryKey: KEYS.detail(id) });
    },
  });
}

export { KEYS as knowledgeBaseKeys };

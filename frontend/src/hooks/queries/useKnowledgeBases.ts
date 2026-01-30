/**
 * 知识库相关 React Query Hooks
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listKnowledgeBases,
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
} from '../../services/knowledgeBases';
import { indexRebuildKeys } from './useIndexRebuilds';

// Query Keys
const KEYS = {
  all: ['knowledgeBases'] as const,
  list: () => [...KEYS.all, 'list'] as const,
  detail: (id: string) => [...KEYS.all, 'detail', id] as const,
};

/**
 * 获取知识库列表
 */
export function useKnowledgeBases(params?: { status?: KnowledgeBaseStatusFilter }) {
  const status = params?.status ?? 'active';
  return useQuery({
    queryKey: [...KEYS.list(), status],
    queryFn: () => listKnowledgeBases({ status }).then((res) => res.items),
  });
}

/**
 * 获取知识库详情
 */
export function useKnowledgeBase(id: string) {
  return useQuery({
    queryKey: KEYS.detail(id),
    queryFn: () => getKnowledgeBase(id),
    enabled: !!id,
  });
}

/**
 * 创建知识库
 */
export function useCreateKnowledgeBase() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: KnowledgeBaseCreate) => createKnowledgeBase(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.list() });
    },
  });
}

/**
 * 更新知识库
 */
export function useUpdateKnowledgeBase() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: KnowledgeBaseUpdate }) =>
      updateKnowledgeBase(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: KEYS.list() });
      queryClient.invalidateQueries({ queryKey: KEYS.detail(id) });
    },
  });
}

/**
 * 更新知识库索引配置（触发重建）
 */
export function useUpdateKnowledgeBaseIndexConfig() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, index_config }: { id: string; index_config: IndexConfig }) =>
      updateKnowledgeBaseIndexConfig(id, index_config),
    onSuccess: (res: KnowledgeBaseIndexConfigUpdateResponse, { id }) => {
      queryClient.invalidateQueries({ queryKey: KEYS.list() });
      queryClient.setQueryData(KEYS.detail(id), res.knowledge_base);
      if (res.rebuild_job) {
        queryClient.setQueryData(indexRebuildKeys.job(res.rebuild_job.id), res.rebuild_job);
      }
    },
  });
}

/**
 * 删除知识库
 */
export function useDeleteKnowledgeBase() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => deleteKnowledgeBase(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.list() });
    },
  });
}

/**
 * 归档知识库
 */
export function useArchiveKnowledgeBase() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => archiveKnowledgeBase(id),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: KEYS.list() });
      queryClient.invalidateQueries({ queryKey: KEYS.detail(id) });
    },
  });
}

export { KEYS as knowledgeBaseKeys };

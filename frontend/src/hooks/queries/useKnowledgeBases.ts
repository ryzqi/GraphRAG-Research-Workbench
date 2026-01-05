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
  type KnowledgeBaseCreate,
  type KnowledgeBaseUpdate,
} from '../../services/knowledgeBases';

// Query Keys
const KEYS = {
  all: ['knowledgeBases'] as const,
  list: () => [...KEYS.all, 'list'] as const,
  detail: (id: string) => [...KEYS.all, 'detail', id] as const,
};

/**
 * 获取知识库列表
 */
export function useKnowledgeBases() {
  return useQuery({
    queryKey: KEYS.list(),
    queryFn: () => listKnowledgeBases().then((res) => res.items),
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

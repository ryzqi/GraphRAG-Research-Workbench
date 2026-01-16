/**
 * 扩展管理 React Query Hooks
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createExtension,
  deleteExtension,
  getExtensionTools,
  listExtensions,
  updateExtension,
  type ToolExtensionCreate,
  type ToolExtensionUpdate,
} from '../../services/extensions';

// Query Keys
const KEYS = {
  all: ['extensions'] as const,
  list: () => [...KEYS.all, 'list'] as const,
  detail: (id: string) => [...KEYS.all, 'detail', id] as const,
  tools: (id: string) => [...KEYS.all, 'tools', id] as const,
};

/**
 * 获取扩展列表
 */
export function useExtensions() {
  return useQuery({
    queryKey: KEYS.list(),
    queryFn: () => listExtensions().then((res) => res.items),
  });
}

/**
 * 获取扩展提供的工具列表
 */
export function useExtensionTools(extensionId: string | undefined) {
  return useQuery({
    queryKey: KEYS.tools(extensionId!),
    queryFn: () => getExtensionTools(extensionId!).then((res) => res.items),
    enabled: !!extensionId,
  });
}

/**
 * 创建扩展
 */
export function useCreateExtension() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ToolExtensionCreate) => createExtension(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.list() });
    },
  });
}

/**
 * 更新扩展
 */
export function useUpdateExtension() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ToolExtensionUpdate }) =>
      updateExtension(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: KEYS.list() });
      queryClient.invalidateQueries({ queryKey: KEYS.detail(id) });
      queryClient.invalidateQueries({ queryKey: KEYS.tools(id) });
    },
  });
}

/**
 * 删除扩展
 */
export function useDeleteExtension() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => deleteExtension(id),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: KEYS.list() });
      queryClient.removeQueries({ queryKey: KEYS.detail(id) });
      queryClient.removeQueries({ queryKey: KEYS.tools(id) });
    },
  });
}

export { KEYS as extensionKeys };

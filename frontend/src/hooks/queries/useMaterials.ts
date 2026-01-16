/**
 * 资料相关 React Query Hooks
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createTextMaterial,
  createUrlMaterial,
  listMaterials,
  uploadMaterial,
  type MaterialCreateText,
  type MaterialCreateUrl,
} from '../../services/materials';

// Query Keys
const NO_ID = '__none__';

const KEYS = {
  all: ['materials'] as const,
  list: (kbId: string | undefined) => [...KEYS.all, 'list', kbId ?? NO_ID] as const,
};

/**
 * 获取知识库资料列表
 */
export function useMaterials(kbId: string | undefined) {
  return useQuery({
    queryKey: KEYS.list(kbId),
    queryFn: () => listMaterials(kbId as string).then((res) => res.items),
    enabled: !!kbId,
  });
}

/**
 * 创建文本资料
 */
export function useCreateTextMaterial() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ kbId, data }: { kbId: string; data: MaterialCreateText }) =>
      createTextMaterial(kbId, data),
    onSuccess: (_, { kbId }) => {
      queryClient.invalidateQueries({ queryKey: KEYS.list(kbId) });
    },
  });
}

/**
 * 创建 URL 资料
 */
export function useCreateUrlMaterial() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ kbId, data }: { kbId: string; data: MaterialCreateUrl }) =>
      createUrlMaterial(kbId, data),
    onSuccess: (_, { kbId }) => {
      queryClient.invalidateQueries({ queryKey: KEYS.list(kbId) });
    },
  });
}

/**
 * 上传文件资料
 */
export function useUploadMaterial() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      kbId,
      title,
      file,
    }: {
      kbId: string;
      title: string;
      file: File;
    }) => uploadMaterial(kbId, title, file),
    onSuccess: (_, { kbId }) => {
      queryClient.invalidateQueries({ queryKey: KEYS.list(kbId) });
    },
  });
}

export { KEYS as materialKeys };

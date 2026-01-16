/**
 * 反馈相关 React Query Hooks
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  listFeedback,
  updateFeedback,
  type FeedbackStatus,
  type FeedbackUpdate,
} from '../../services/feedback';

// Query Keys
const KEYS = {
  all: ['feedback'] as const,
  list: (status: FeedbackStatus | '') => [...KEYS.all, 'list', status || 'all'] as const,
  detail: (id: string) => [...KEYS.all, 'detail', id] as const,
};

/**
 * 获取反馈列表（可按状态筛选）
 */
export function useFeedbackList(status: FeedbackStatus | '') {
  return useQuery({
    queryKey: KEYS.list(status),
    queryFn: () => listFeedback(status ? { status } : undefined).then((res) => res.items),
  });
}

/**
 * 更新反馈状态/处理说明
 */
export function useUpdateFeedback() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: FeedbackUpdate }) =>
      updateFeedback(id, data),
    onSuccess: (_, { id }) => {
      // 列表/详情都失效，避免筛选条件导致的数据不一致。
      queryClient.invalidateQueries({ queryKey: KEYS.all });
      queryClient.invalidateQueries({ queryKey: KEYS.detail(id) });
    },
  });
}

export { KEYS as feedbackKeys };

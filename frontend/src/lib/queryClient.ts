/**
 * React Query 客户端配置
 */
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 5 分钟内数据视为新鲜
      staleTime: 1000 * 60 * 5,
      // 30 分钟后垃圾回收
      gcTime: 1000 * 60 * 30,
      // 失败时重试 1 次
      retry: 1,
      // 窗口聚焦时不自动刷新
      refetchOnWindowFocus: false,
    },
    mutations: {
      // 失败时重试 0 次
      retry: 0,
    },
  },
});

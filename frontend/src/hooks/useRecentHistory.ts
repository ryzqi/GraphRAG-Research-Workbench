/**
 * Recent 历史管理 Hook
 * 基于 React Query 共享 Recent 列表
 */
import { useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { deleteChatSession, getRecentChats } from '../services/chats';

export interface RecentSession {
  sessionId: string;
  title: string;
  type: 'general_chat' | 'kb_chat';
  updatedAt: string;
}

const MAX_RECENT = 20;
const RECENT_QUERY_KEY = ['chats', 'recent', MAX_RECENT] as const;

type RecentHistoryData = {
  sessions: RecentSession[];
  webSearchAvailable: boolean;
};

export function useRecentHistory() {
  const queryClient = useQueryClient();
  const recentQuery = useQuery<RecentHistoryData>({
    queryKey: RECENT_QUERY_KEY,
    queryFn: async () => {
      const data = await getRecentChats(MAX_RECENT);
      return {
        sessions: data.items.map((item) => ({
          sessionId: item.id,
          title: item.title ?? '',
          type: item.session_type,
          updatedAt: item.updated_at,
        })),
        webSearchAvailable: Boolean(data.web_search_available),
      };
    },
  });

  // 添加或更新会话（本地更新 + 后台刷新）
  const upsertSession = useCallback(
    (session: RecentSession) => {
      queryClient.setQueryData<RecentHistoryData>(RECENT_QUERY_KEY, (prev) => {
        const updated = { ...session, updatedAt: new Date().toISOString() };
        if (!prev) {
          return { sessions: [updated], webSearchAvailable: false };
        }
        const filtered = prev.sessions.filter((s) => s.sessionId !== session.sessionId);
        return {
          ...prev,
          sessions: [updated, ...filtered].slice(0, MAX_RECENT),
        };
      });
      void queryClient.invalidateQueries({ queryKey: RECENT_QUERY_KEY });
    },
    [queryClient]
  );

  // 删除会话（仅本地）
  const removeSession = useCallback(
    (sessionId: string) => {
      queryClient.setQueryData<RecentHistoryData>(RECENT_QUERY_KEY, (prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          sessions: prev.sessions.filter((s) => s.sessionId !== sessionId),
        };
      });
      void deleteChatSession(sessionId)
        .catch(() => null)
        .finally(() => {
          void queryClient.invalidateQueries({ queryKey: RECENT_QUERY_KEY });
        });
    },
    [queryClient]
  );

  // 清空历史（仅本地）
  const clearHistory = useCallback(() => {
    queryClient.setQueryData<RecentHistoryData>(RECENT_QUERY_KEY, (prev) => {
      if (!prev) {
        return { sessions: [], webSearchAvailable: false };
      }
      return { ...prev, sessions: [] };
    });
  }, [queryClient]);

  const refresh = useCallback(() => {
    return queryClient.invalidateQueries({ queryKey: RECENT_QUERY_KEY });
  }, [queryClient]);

  return {
    sessions: recentQuery.data?.sessions ?? [],
    upsertSession,
    removeSession,
    clearHistory,
    webSearchAvailable: recentQuery.data?.webSearchAvailable ?? false,
    refresh,
  };
}

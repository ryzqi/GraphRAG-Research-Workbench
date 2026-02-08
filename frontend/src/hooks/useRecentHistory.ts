/**
 * Recent history hook using SWR shared cache
 */
import { useCallback } from 'react';
import { useSWRConfig } from 'swr';
import { useApiQuery } from '../lib/swr';
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
  const { mutate } = useSWRConfig();

  const recentQuery = useApiQuery<RecentHistoryData>(RECENT_QUERY_KEY, async () => {
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
  });

  const upsertSession = useCallback(
    (session: RecentSession) => {
      void mutate<RecentHistoryData>(
        RECENT_QUERY_KEY,
        (prev) => {
          const updated = { ...session, updatedAt: new Date().toISOString() };
          if (!prev) {
            return { sessions: [updated], webSearchAvailable: false };
          }
          const filtered = prev.sessions.filter((s) => s.sessionId !== session.sessionId);
          return {
            ...prev,
            sessions: [updated, ...filtered].slice(0, MAX_RECENT),
          };
        },
        { revalidate: false }
      );
    },
    [mutate]
  );

  const removeSession = useCallback(
    (sessionId: string) => {
      void mutate<RecentHistoryData>(
        RECENT_QUERY_KEY,
        (prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            sessions: prev.sessions.filter((s) => s.sessionId !== sessionId),
          };
        },
        { revalidate: false }
      );

      void deleteChatSession(sessionId).catch(() => {
        void mutate(RECENT_QUERY_KEY);
      });
    },
    [mutate]
  );

  const clearHistory = useCallback(() => {
    void mutate<RecentHistoryData>(
      RECENT_QUERY_KEY,
      (prev) => {
        if (!prev) {
          return { sessions: [], webSearchAvailable: false };
        }
        return { ...prev, sessions: [] };
      },
      { revalidate: false }
    );
  }, [mutate]);

  const refresh = useCallback(() => {
    return mutate(RECENT_QUERY_KEY);
  }, [mutate]);

  return {
    sessions: recentQuery.data?.sessions ?? [],
    upsertSession,
    removeSession,
    clearHistory,
    webSearchAvailable: recentQuery.data?.webSearchAvailable ?? false,
    refresh,
  };
}

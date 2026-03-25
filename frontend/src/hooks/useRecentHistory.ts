/**
 * Recent history hook using SWR shared cache
 */
import { useCallback } from 'react';
import { useSWRConfig } from 'swr';
import { useApiQuery } from '../lib/swr';
import {
  deleteChatSession,
  getRecentChats,
  type WebSearchStatus,
} from '../services/chats';

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
  webSearch: WebSearchStatus;
};

const DEFAULT_WEB_SEARCH_STATUS: WebSearchStatus = {
  configured: false,
  verified: false,
  healthy: false,
};

export const recentHistoryQueryKey = RECENT_QUERY_KEY;

export function toRecentHistoryData(input: {
  items: Array<{
    id: string;
    title: string | null;
    session_type: 'general_chat' | 'kb_chat';
    updated_at: string;
  }>;
  web_search: WebSearchStatus;
}): RecentHistoryData {
  return {
    sessions: input.items.map((item) => ({
      sessionId: item.id,
      title: item.title ?? '',
      type: item.session_type,
      updatedAt: item.updated_at,
    })),
    webSearch: input.web_search ?? DEFAULT_WEB_SEARCH_STATUS,
  };
}

export function useRecentHistory() {
  const { mutate } = useSWRConfig();

  const recentQuery = useApiQuery<RecentHistoryData>(RECENT_QUERY_KEY, async () => {
    const data = await getRecentChats(MAX_RECENT);
    return toRecentHistoryData(data);
  }, {
    skipInitialFetchIfCached: true,
  });

  const upsertSession = useCallback(
    (session: RecentSession) => {
      void mutate<RecentHistoryData>(
        RECENT_QUERY_KEY,
        (prev) => {
          const updated = { ...session, updatedAt: new Date().toISOString() };
          if (!prev) {
            return { sessions: [updated], webSearch: DEFAULT_WEB_SEARCH_STATUS };
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
          return { sessions: [], webSearch: DEFAULT_WEB_SEARCH_STATUS };
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
    webSearch: recentQuery.data?.webSearch ?? DEFAULT_WEB_SEARCH_STATUS,
    refresh,
  };
}

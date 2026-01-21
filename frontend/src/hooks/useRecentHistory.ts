/**
 * Recent 历史管理 Hook
 * 从服务端读取最近对话列表
 */
import { useCallback, useEffect, useState } from 'react';
import { deleteChatSession, getRecentChats } from '../services/chats';

export interface RecentSession {
  sessionId: string;
  title: string;
  type: 'general_chat' | 'kb_chat';
  updatedAt: string;
}

const MAX_RECENT = 20;

export function useRecentHistory() {
  const [sessions, setSessions] = useState<RecentSession[]>([]);
  const [webSearchAvailable, setWebSearchAvailable] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await getRecentChats(MAX_RECENT);
      const mapped = data.items.map((item) => ({
        sessionId: item.id,
        title: item.title ?? '',
        type: item.session_type,
        updatedAt: item.updated_at,
      }));
      setSessions(mapped.slice(0, MAX_RECENT));
      setWebSearchAvailable(Boolean(data.web_search_available));
    } catch {
      // 保持静默失败，避免影响主流程
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 添加或更新会话（本地更新 + 后台刷新）
  const upsertSession = useCallback(
    (session: RecentSession) => {
      setSessions((prev) => {
        const filtered = prev.filter((s) => s.sessionId !== session.sessionId);
        return [{ ...session, updatedAt: new Date().toISOString() }, ...filtered].slice(
          0,
          MAX_RECENT
        );
      });
      void refresh();
    },
    [refresh]
  );

  // 删除会话（仅本地）
  const removeSession = useCallback((sessionId: string) => {
    setSessions((prev) => prev.filter((s) => s.sessionId !== sessionId));
    void deleteChatSession(sessionId)
      .then(() => refresh())
      .catch(() => refresh());
  }, [refresh]);

  // 清空历史（仅本地）
  const clearHistory = useCallback(() => {
    setSessions([]);
  }, []);

  return {
    sessions,
    upsertSession,
    removeSession,
    clearHistory,
    webSearchAvailable,
    refresh,
  };
}

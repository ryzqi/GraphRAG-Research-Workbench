/**
 * Recent 历史管理 Hook
 * 使用 localStorage 实现本地持久化（最佳努力）
 */
import { useCallback, useEffect, useState } from 'react';

export interface RecentSession {
  sessionId: string;
  title: string;
  type: 'general_chat' | 'kb_chat';
  updatedAt: string;
}

const STORAGE_KEY = 'gemini-recent-sessions';
const MAX_RECENT = 20;

function loadFromStorage(): RecentSession[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.slice(0, MAX_RECENT);
  } catch {
    return [];
  }
}

function saveToStorage(sessions: RecentSession[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.slice(0, MAX_RECENT)));
  } catch {
    // 静默失败
  }
}

export function useRecentHistory() {
  const [sessions, setSessions] = useState<RecentSession[]>(() => loadFromStorage());

  // 同步到 localStorage
  useEffect(() => {
    saveToStorage(sessions);
  }, [sessions]);

  // 添加或更新会话
  const upsertSession = useCallback((session: RecentSession) => {
    setSessions((prev) => {
      const filtered = prev.filter((s) => s.sessionId !== session.sessionId);
      return [{ ...session, updatedAt: new Date().toISOString() }, ...filtered].slice(0, MAX_RECENT);
    });
  }, []);

  // 删除会话
  const removeSession = useCallback((sessionId: string) => {
    setSessions((prev) => prev.filter((s) => s.sessionId !== sessionId));
  }, []);

  // 清空历史
  const clearHistory = useCallback(() => {
    setSessions([]);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  return {
    sessions,
    upsertSession,
    removeSession,
    clearHistory,
  };
}

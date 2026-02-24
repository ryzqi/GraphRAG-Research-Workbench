import { useEffect, useMemo, useRef } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { ChatMessage } from '../components/chat/MessageList';
import type { ChatSession, KbChatConfig } from '../services/chats';
import { getChatMessages, getChatSession } from '../services/chats';
import { HttpError } from '../services/http';
import {
  buildChatSessionRequestKey,
  ChatSessionRequestControl,
} from '../services/chatSessionRequestControl';
import { getErrorMessage } from '../lib/errorHandler';

interface UseKbChatSessionControllerParams {
  sessionId: string | null;
  pathname: string;
  clearSessionIdFromUrl: () => void;
  setLoadingSession: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setSession: Dispatch<SetStateAction<ChatSession | null>>;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setSelectedKbIds: Dispatch<SetStateAction<string[]>>;
  setKbChatConfig: Dispatch<SetStateAction<KbChatConfig>>;
  defaultConfig: KbChatConfig;
}

export function useKbChatSessionController(params: UseKbChatSessionControllerParams) {
  const {
    sessionId,
    pathname,
    clearSessionIdFromUrl,
    setLoadingSession,
    setError,
    setSession,
    setMessages,
    setSelectedKbIds,
    setKbChatConfig,
    defaultConfig,
  } = params;

  const sessionRequestKey = useMemo(
    () => buildChatSessionRequestKey({ scope: 'kb', sessionId, contextId: pathname }),
    [pathname, sessionId]
  );
  const requestControlRef = useRef(new ChatSessionRequestControl());

  useEffect(() => {
    if (!sessionId || !sessionRequestKey) {
      return;
    }
    const requestControl = requestControlRef.current;
    const request = requestControl.start(sessionRequestKey);
    const loadSession = async () => {
      setLoadingSession(true);
      setError(null);
      try {
        const [loadedSession, history] = await Promise.all([
          getChatSession(sessionId, request.signal),
          getChatMessages(sessionId, request.signal),
        ]);
        if (!requestControl.isLatest(request.id, sessionRequestKey)) return;
        setSession(loadedSession);
        setSelectedKbIds(loadedSession.selected_kb_ids ?? []);
        setKbChatConfig(loadedSession.kb_chat_config ?? defaultConfig);
        setMessages(
          history.map((msg) => ({
            id: msg.id,
            role: msg.role === 'assistant' ? 'assistant' : 'user',
            content: msg.content,
          }))
        );
      } catch (e) {
        if (!requestControl.isLatest(request.id, sessionRequestKey)) return;
        if (request.signal.aborted) return;
        if (e instanceof HttpError && e.status === 404) {
          setSession(null);
          setMessages([]);
          setSelectedKbIds([]);
          setKbChatConfig(defaultConfig);
          clearSessionIdFromUrl();
          return;
        }
        setError(getErrorMessage(e));
      } finally {
        if (requestControl.isLatest(request.id, sessionRequestKey)) {
          setLoadingSession(false);
          requestControl.finish(request.id);
        }
      }
    };
    void loadSession();
    return () => {
      requestControl.cancelActive();
    };
  }, [
    clearSessionIdFromUrl,
    defaultConfig,
    sessionId,
    sessionRequestKey,
    setError,
    setKbChatConfig,
    setLoadingSession,
    setMessages,
    setSelectedKbIds,
    setSession,
  ]);

  useEffect(() => {
    if (sessionId) return;
    setSession(null);
    setMessages([]);
    setError(null);
    setKbChatConfig(defaultConfig);
  }, [defaultConfig, sessionId, setError, setKbChatConfig, setMessages, setSession]);
}

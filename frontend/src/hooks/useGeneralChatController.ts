import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { ChatMessage } from '../components/chat/MessageList';
import {
  applyMessagesEventToState,
  createMessageStateBatcher,
} from '../services/chatStreamDeltas';
import {
  buildChatSessionRequestKey,
  ChatSessionRequestControl,
} from '../services/chatSessionRequestControl';
import {
  createChatSession,
  getChatMessages,
  getChatSession,
  resumeToolApproval,
  sendMessage,
  streamChatMessage,
  streamResumeToolApproval,
  type ChatMessageResponse,
  type ChatPendingToolApprovalResponse,
  type ChatSession,
  type ToolApprovalRequest,
} from '../services/chats';
import { HttpError } from '../services/http';
import { parseSseJson } from '../lib/sse';
import { completeMessageState, createMessageState } from '../lib/deltaParser';
import { useRecentHistory } from './useRecentHistory';

function isPendingClarification(
  response: ChatMessageResponse
): response is Extract<ChatMessageResponse, { status: 'pending_user_clarification' }> {
  return response.status === 'pending_user_clarification';
}

function isPendingToolApproval(
  response: ChatMessageResponse
): response is ChatPendingToolApprovalResponse {
  return response.status === 'pending_tool_approval';
}

function isAbortLikeError(error: unknown): boolean {
  if (error instanceof HttpError && error.status === 499) {
    return true;
  }
  if ((error as { name?: string } | undefined)?.name === 'AbortError') {
    return true;
  }
  return false;
}

function toPendingToolApprovalState(
  response: ChatPendingToolApprovalResponse
): NonNullable<ChatMessage['pendingToolApproval']> {
  return {
    interrupts: response.pending_interrupts.map((interrupt) => ({
      interrupt_id: interrupt.interrupt_id,
      message: interrupt.message,
      toolCalls: interrupt.pending_tool_calls.map((call) => ({
        tool_name: call.tool_name,
        extension_name: call.extension_name ?? undefined,
      })),
    })),
  };
}

export function useGeneralChatController() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const sessionId = searchParams.get('sessionId');
  const sessionRequestKey = useMemo(
    () => buildChatSessionRequestKey({ scope: 'general', sessionId, contextId: pathname }),
    [pathname, sessionId]
  );
  const requestControlRef = useRef(new ChatSessionRequestControl());
  const streamAbortRef = useRef<AbortController | null>(null);

  const abortActiveStream = useCallback(() => {
    if (streamAbortRef.current) {
      streamAbortRef.current.abort();
      streamAbortRef.current = null;
    }
  }, []);

  const replaceSearchParams = useCallback(
    (next: URLSearchParams) => {
      const query = next.toString();
      const href = query ? `${pathname}?${query}` : pathname;
      router.replace(href);
    },
    [pathname, router]
  );

  const clearSessionIdFromUrl = useCallback(() => {
    if (typeof window === 'undefined') {
      return;
    }
    const nextParams = new URLSearchParams(window.location.search);
    nextParams.delete('sessionId');
    replaceSearchParams(nextParams);
  }, [replaceSearchParams]);

  const [session, setSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [allowExternal, setAllowExternal] = useState(false);
  const { upsertSession, webSearchAvailable } = useRecentHistory();

  const hasPendingApproval = messages.some((m) => Boolean(m.pendingToolApproval));
  const isInputDisabled = loading || loadingSession || hasPendingApproval;

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
        setAllowExternal(loadedSession.allow_external);
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
          setError(null);
          clearSessionIdFromUrl();
          return;
        }
        setError(e instanceof Error ? e.message : '加载会话失败');
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
      abortActiveStream();
    };
  }, [sessionId, sessionRequestKey, clearSessionIdFromUrl, abortActiveStream]);

  useEffect(() => {
    if (sessionId) return;
    abortActiveStream();
    setSession(null);
    setMessages([]);
    setLoading(false);
    setLoadingSession(false);
    setError(null);
  }, [sessionId, abortActiveStream]);

  const updateMessage = useCallback((id: string, updater: (msg: ChatMessage) => ChatMessage) => {
    setMessages((prev) => {
      const lastIndex = prev.length - 1;
      if (lastIndex >= 0 && prev[lastIndex].id === id) {
        const next = prev.slice();
        next[lastIndex] = updater(prev[lastIndex]);
        return next;
      }
      const index = prev.findIndex((msg) => msg.id === id);
      if (index === -1) {
        return prev;
      }
      const next = prev.slice();
      next[index] = updater(prev[index]);
      return next;
    });
  }, []);

  const createSession = useCallback(async () => {
    const newSession = await createChatSession({
      session_type: 'general_chat',
      allow_external: allowExternal,
      mode: 'single_agent',
    });
    setSession(newSession);
    return newSession;
  }, [allowExternal]);

  const handleNewChat = useCallback(() => {
    abortActiveStream();
    setSession(null);
    setMessages([]);
    setInput('');
    setLoading(false);
    setLoadingSession(false);
    setError(null);
  }, [abortActiveStream]);

  const handleSend = useCallback(async () => {
    const content = input.trim();
    if (!content || loading || loadingSession || hasPendingApproval) return;

    const userMessage: ChatMessage = { id: `user-${Date.now()}`, role: 'user', content };
    const assistantId = `assistant-${Date.now()}`;
    let msgState = createMessageState();

    setMessages((prev) => [
      ...prev,
      userMessage,
      { id: assistantId, role: 'assistant', content: '', think: '', isStreaming: true },
    ]);
    setInput('');
    setLoading(true);
    setError(null);

    try {
      const currentSession = session ?? (await createSession());
      upsertSession({
        sessionId: currentSession.id,
        title: '普通对话',
        type: currentSession.session_type,
        updatedAt: currentSession.updated_at,
      });

      if (!sessionId || currentSession.id !== sessionId) {
        const nextParams = new URLSearchParams(searchParams.toString());
        nextParams.set('sessionId', currentSession.id);
        replaceSearchParams(nextParams);
      }

      let hadStreamEvent = false;
      const deltaBatcher = createMessageStateBatcher((nextState) => {
        msgState = nextState;
        updateMessage(assistantId, (msg) => ({
          ...msg,
          content: nextState.final_content,
          think: nextState.thought_log,
          toolSteps: nextState.tool_steps,
        }));
      });

      const fallbackToJson = async () => {
        const response = await sendMessage(currentSession.id, content);
        if (isPendingClarification(response)) {
          updateMessage(assistantId, (msg) => ({
            ...msg,
            content: response.message,
            isStreaming: false,
            pendingClarification: {
              message: response.message,
              pendingClarification: response.pending_clarification ?? null,
            },
            runId: response.run.id,
          }));
          return;
        }
        if (isPendingToolApproval(response)) {
          updateMessage(assistantId, (msg) => ({
            ...msg,
            isStreaming: false,
            pendingToolApproval: toPendingToolApprovalState(response),
            runId: response.run.id,
          }));
          return;
        }
        if (response.status !== 'succeeded') {
          throw new Error('发送消息返回了不支持的状态');
        }
        updateMessage(assistantId, (msg) => ({
          ...msg,
          content: response.assistant_message.content,
          isStreaming: false,
          runId: response.run.id,
          evidence: response.evidence,
        }));
      };

      let sawFinalEvent = false;
      let streamAbortController: AbortController | null = null;
      try {
        streamAbortController = new AbortController();
        streamAbortRef.current = streamAbortController;
        const stream = await streamChatMessage(
          currentSession.id,
          content,
          streamAbortController.signal
        );
        for await (const event of stream) {
          if (event.event === 'meta') {
            hadStreamEvent = true;
            const data = parseSseJson<{ run_id?: string }>(event.data);
            if (data?.run_id) {
              updateMessage(assistantId, (msg) => ({ ...msg, runId: data.run_id }));
            }
            continue;
          }
          if (event.event === 'delta' || event.event === 'messages') {
            hadStreamEvent = true;
            const data = parseSseJson<Record<string, unknown>>(event.data);
            msgState = applyMessagesEventToState(msgState, data);
            deltaBatcher.push(msgState);
            continue;
          }
          if (event.event === 'pending_user_clarification') {
            hadStreamEvent = true;
            const data = parseSseJson<
              Partial<Extract<ChatMessageResponse, { status: 'pending_user_clarification' }>> & {
                run_id?: string;
              }
            >(event.data);
            deltaBatcher.flush();
            updateMessage(assistantId, (msg) => ({
              ...msg,
              isStreaming: false,
              pendingClarification: {
                message: data?.message ?? '',
                pendingClarification: data?.pending_clarification ?? null,
              },
              runId: data?.run_id ?? msg.runId,
            }));
            continue;
          }
          if (event.event === 'pending_tool_approval' || event.event === 'interrupt') {
            hadStreamEvent = true;
            const data = parseSseJson<ChatMessageResponse>(event.data);
            if (!isPendingToolApproval(data)) {
              throw new Error('工具审批事件格式无效');
            }
            deltaBatcher.flush();
            updateMessage(assistantId, (msg) => ({
              ...msg,
              isStreaming: false,
              pendingToolApproval: toPendingToolApprovalState(data),
              runId: data.run.id,
            }));
            continue;
          }
          if (event.event === 'final') {
            hadStreamEvent = true;
            sawFinalEvent = true;
            deltaBatcher.flush();
            const data = parseSseJson<ChatMessageResponse>(event.data);
            if (isPendingToolApproval(data)) {
              updateMessage(assistantId, (msg) => ({
                ...msg,
                isStreaming: false,
                pendingToolApproval: toPendingToolApprovalState(data),
                runId: data.run.id,
              }));
              continue;
            }
            if (data.status !== 'succeeded') {
              throw new Error('发送消息返回了不支持的状态');
            }
            const mergedContent = msgState.final_content.trim()
              ? msgState.final_content
              : data.assistant_message.content;
            updateMessage(assistantId, (msg) => ({
              ...msg,
              content: mergedContent,
              think: msgState.thought_log,
              toolSteps: msgState.tool_steps,
              isStreaming: false,
              runId: data.run.id,
              evidence: data.evidence,
            }));
            continue;
          }
          if (event.event === 'error') {
            deltaBatcher.flush();
            const err = parseSseJson<{ message?: string }>(event.data);
            throw new Error(err?.message ?? '发送消息失败');
          }
        }
        deltaBatcher.flush();
        if (!sawFinalEvent) {
          msgState = completeMessageState(msgState);
          updateMessage(assistantId, (msg) => ({
            ...msg,
            content: msgState.final_content,
            think: msgState.thought_log,
            toolSteps: msgState.tool_steps,
            isStreaming: false,
          }));
        }
      } catch (e) {
        if (hadStreamEvent) {
          if (!isAbortLikeError(e)) {
            setError(e instanceof Error ? e.message : '发送消息失败');
          }
          setLoading(false);
          return;
        }
        await fallbackToJson();
      } finally {
        if (streamAbortRef.current === streamAbortController) {
          streamAbortRef.current = null;
        }
        deltaBatcher.flush();
      }
    } catch (e) {
      if (!isAbortLikeError(e)) {
        setError(e instanceof Error ? e.message : '发送消息失败');
      }
      updateMessage(assistantId, (msg) => ({ ...msg, isStreaming: false }));
    } finally {
      setLoading(false);
    }
  }, [
    createSession,
    hasPendingApproval,
    input,
    loading,
    loadingSession,
    replaceSearchParams,
    searchParams,
    session,
    sessionId,
    upsertSession,
    updateMessage,
  ]);

  const handleToolApproval = useCallback(
    async (messageId: string, runId: string, approval: ToolApprovalRequest) => {
      if (!session || loading) return;
      setLoading(true);
      setError(null);
      const pendingMessageId = messageId;
      let msgState = createMessageState();
      const deltaBatcher = createMessageStateBatcher((nextState) => {
        msgState = nextState;
        updateMessage(pendingMessageId, (msg) => ({
          ...msg,
          content: nextState.final_content || msg.content,
          think: nextState.thought_log,
          toolSteps: nextState.tool_steps,
        }));
      });

      const fallbackToJson = async () => {
        const response = await resumeToolApproval(session.id, runId, approval);
        if (response.status !== 'succeeded') {
          throw new Error('恢复执行返回了不支持的状态');
        }
        updateMessage(pendingMessageId, (msg) => ({
          ...msg,
          content: response.assistant_message.content,
          pendingToolApproval: undefined,
          runId: response.run.id,
          isStreaming: false,
          evidence: response.evidence,
        }));
      };

      let hadStreamEvent = false;
      let sawFinalEvent = false;
      let streamAbortController: AbortController | null = null;
      try {
        updateMessage(pendingMessageId, (msg) => ({
          ...msg,
          pendingToolApproval: undefined,
          isStreaming: true,
        }));
        streamAbortController = new AbortController();
        streamAbortRef.current = streamAbortController;
        const stream = await streamResumeToolApproval(
          session.id,
          runId,
          approval,
          streamAbortController.signal
        );
        for await (const event of stream) {
          if (event.event === 'meta') {
            hadStreamEvent = true;
            const data = parseSseJson<{ run_id?: string }>(event.data);
            if (data?.run_id) {
              updateMessage(pendingMessageId, (msg) => ({ ...msg, runId: data.run_id }));
            }
            continue;
          }
          if (event.event === 'delta' || event.event === 'messages') {
            hadStreamEvent = true;
            const data = parseSseJson<Record<string, unknown>>(event.data);
            msgState = applyMessagesEventToState(msgState, data);
            deltaBatcher.push(msgState);
            continue;
          }
          if (event.event === 'pending_tool_approval' || event.event === 'interrupt') {
            hadStreamEvent = true;
            const data = parseSseJson<ChatMessageResponse>(event.data);
            if (!isPendingToolApproval(data)) {
              throw new Error('工具审批事件格式无效');
            }
            deltaBatcher.flush();
            updateMessage(pendingMessageId, (msg) => ({
              ...msg,
              isStreaming: false,
              pendingToolApproval: toPendingToolApprovalState(data),
              runId: data.run.id,
            }));
            continue;
          }
          if (event.event === 'final') {
            hadStreamEvent = true;
            sawFinalEvent = true;
            deltaBatcher.flush();
            const data = parseSseJson<ChatMessageResponse>(event.data);
            if (isPendingToolApproval(data)) {
              updateMessage(pendingMessageId, (msg) => ({
                ...msg,
                isStreaming: false,
                pendingToolApproval: toPendingToolApprovalState(data),
                runId: data.run.id,
              }));
              continue;
            }
            if (data.status !== 'succeeded') {
              throw new Error('恢复执行返回了不支持的状态');
            }
            const mergedContent = msgState.final_content.trim()
              ? msgState.final_content
              : data.assistant_message.content;
            updateMessage(pendingMessageId, (msg) => ({
              ...msg,
              content: mergedContent,
              think: msgState.thought_log,
              toolSteps: msgState.tool_steps,
              pendingToolApproval: undefined,
              runId: data.run.id,
              isStreaming: false,
              evidence: data.evidence,
            }));
            continue;
          }
          if (event.event === 'error') {
            deltaBatcher.flush();
            const err = parseSseJson<{ message?: string }>(event.data);
            throw new Error(err?.message ?? '恢复执行失败');
          }
        }

        deltaBatcher.flush();
        if (!sawFinalEvent) {
          msgState = completeMessageState(msgState);
          updateMessage(pendingMessageId, (msg) => ({
            ...msg,
            content: msgState.final_content,
            think: msgState.thought_log,
            toolSteps: msgState.tool_steps,
            isStreaming: false,
          }));
        }
      } catch (e) {
        if (hadStreamEvent) {
          if (!isAbortLikeError(e)) {
            setError(e instanceof Error ? e.message : '恢复执行失败');
          }
          setLoading(false);
          return;
        }
        try {
          await fallbackToJson();
        } catch (fallbackError) {
          setError(fallbackError instanceof Error ? fallbackError.message : '恢复执行失败');
        }
      } finally {
        if (streamAbortRef.current === streamAbortController) {
          streamAbortRef.current = null;
        }
        deltaBatcher.flush();
        setLoading(false);
      }
    },
    [session, loading, updateMessage]
  );

  const handleSuggestionClick = useCallback((value: string) => {
    setInput(value);
  }, []);

  return {
    session,
    messages,
    input,
    loading,
    loadingSession,
    error,
    allowExternal,
    setAllowExternal,
    setError,
    setInput,
    webSearchAvailable,
    hasPendingApproval,
    isInputDisabled,
    handleSend,
    handleNewChat,
    handleToolApproval,
    handleSuggestionClick,
  };
}

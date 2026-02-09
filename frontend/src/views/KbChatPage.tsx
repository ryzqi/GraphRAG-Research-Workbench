'use client';

/**
 * 知识库问答页面（Gemini 风格重构）
 */
import { useCallback, useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Box, Stack, Typography } from '@mui/material';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import { Button } from '../components/ui/Button';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { KnowledgeBaseSelector } from '../components/KnowledgeBaseSelector';

import type { ChatMessage } from '../components/chat/MessageList';

import {
  type AgentMode,
  type ChatSession,
  type ChatMessageResponse,
  createChatSession,
  getChatMessages,
  getChatSession,
  sendMessage,
  streamChatMessage,
} from '../services/chats';
import { HttpError } from '../services/http';
import { useSelectableKnowledgeBases } from '../hooks/queries/useKnowledgeBases';
import { useRecentHistory } from '../hooks/useRecentHistory';
import { WelcomeScreen } from '../components/chat/WelcomeScreen';
import { InputComposer } from '../components/chat/InputComposer';
import { getErrorMessage } from '../lib/errorHandler';
import { parseSseJson } from '../lib/sse';
import {
  applyDelta,
  completeMessageState,
  createMessageState,
  parseDelta,
  type MessageState,
} from '../lib/deltaParser';

const MessageList = dynamic(
  () => import('../components/chat/MessageList').then((mod) => mod.MessageList),
  { ssr: false }
);

function createMessageStateBatcher(onFlush: (nextState: MessageState) => void) {
  let pendingState: MessageState | null = null;
  let rafId: number | null = null;

  const flush = () => {
    if (rafId !== null && typeof window !== 'undefined') {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
    if (!pendingState) {
      return;
    }
    const snapshot = pendingState;
    pendingState = null;
    onFlush(snapshot);
  };

  const push = (nextState: MessageState) => {
    pendingState = nextState;
    if (typeof window === 'undefined') {
      flush();
      return;
    }
    if (rafId !== null) {
      return;
    }

    rafId = window.requestAnimationFrame(() => {
      rafId = null;
      if (!pendingState) {
        return;
      }
      const snapshot = pendingState;
      pendingState = null;
      onFlush(snapshot);
    });
  };

  return { push, flush };
}

export function KbChatPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const sessionId = searchParams.get('sessionId');

  const replaceSearchParams = useCallback(
    (next: URLSearchParams) => {
      const query = next.toString();
      const href = query ? `${pathname}?${query}` : pathname;
      router.replace(href);
    },
    [pathname, router]
  );
  const knowledgeBasesQuery = useSelectableKnowledgeBases();
  const knowledgeBases = knowledgeBasesQuery.data ?? [];

  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { upsertSession } = useRecentHistory();

  const mergedError =
    error ?? (knowledgeBasesQuery.error ? getErrorMessage(knowledgeBasesQuery.error) : null);

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    let active = true;
    const loadSession = async () => {
      setLoadingSession(true);
      setError(null);
      try {
        // Fire both requests together to reduce route hydration latency.
        const [loadedSession, history] = await Promise.all([
          getChatSession(sessionId),
          getChatMessages(sessionId),
        ]);
        if (!active) return;
        setSession(loadedSession);
        setSelectedKbIds(loadedSession.selected_kb_ids ?? []);
        setMessages(
          history.map((msg) => ({
            id: msg.id,
            role: msg.role === 'assistant' ? 'assistant' : 'user',
            content: msg.content,
          }))
        );
      } catch (e) {
        if (!active) return;
        // If the sessionId is stale/deleted, clear it so the user can start a new KB chat.
        // (KB chat needs selected KBs, so we cannot auto-create like general chat.)
        if (e instanceof HttpError && e.status === 404) {
          setSession(null);
          setMessages([]);
          setSelectedKbIds([]);
          const nextParams = new URLSearchParams(searchParams.toString());
          nextParams.delete('sessionId');
          replaceSearchParams(nextParams);
          return;
        }
        setError(getErrorMessage(e));
      } finally {
        if (active) {
          setLoadingSession(false);
        }
      }
    };
    void loadSession();
    return () => {
      active = false;
    };
  }, [sessionId, searchParams, replaceSearchParams]);

  useEffect(() => {
    if (sessionId) return;
    setSession(null);
    setMessages([]);
    setError(null);
  }, [sessionId]);

  const updateMessage = useCallback(
    (id: string, updater: (msg: ChatMessage) => ChatMessage) => {
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
    },
    []
  );

  const handleCloseError = () => {
    if (error) {
      setError(null);
      return;
    }
    knowledgeBasesQuery.refetch();
  };

  const toggleKb = useCallback((kbId: string) => {
    setSelectedKbIds((prev) =>
      prev.includes(kbId) ? prev.filter((id) => id !== kbId) : [...prev, kbId]
    );
  }, []);

  const startSession = useCallback(async () => {
    if (selectedKbIds.length === 0) {
      setError('请至少选择一个知识库');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const newSession = await createChatSession({
        session_type: 'kb_chat',
        selected_kb_ids: selectedKbIds,
        allow_external: false,
        mode: 'single_agent' as AgentMode,
      });
      setSession(newSession);
      setMessages([]);

    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [selectedKbIds]);

  const handleSend = useCallback(async () => {
    if (!session || !input.trim() || loading || loadingSession) return;

    const userContent = input.trim();
    const assistantId = `assistant-${Date.now()}`;
    let msgState = createMessageState();
    setInput('');
    setLoading(true);
    setError(null);

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: userContent,
    };
    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: assistantId, role: 'assistant', content: '', think: '', toolSteps: [], isStreaming: true, thinkStartTime: Date.now() },
    ]);

    let recentTouched = false;
    const touchRecent = () => {
      if (recentTouched) return;
      recentTouched = true;
      upsertSession({
        sessionId: session.id,
        title: userContent.slice(0, 30),
        type: 'kb_chat',
        updatedAt: new Date().toISOString(),
      });
    };

    const fallbackToJson = async () => {
      const response: ChatMessageResponse = await sendMessage(session.id, userContent);
      if (response.status !== 'succeeded') {
        throw new Error('知识库对话不支持工具审批流程');
      }
      touchRecent();
      updateMessage(assistantId, () => ({
        id: response.assistant_message.id,
        role: 'assistant',
        content: response.assistant_message.content,
        evidence: response.evidence,
        isStreaming: false,
      }));
    };

    let hadStreamEvent = false;
    const deltaBatcher = createMessageStateBatcher((nextState) => {
      updateMessage(assistantId, (msg) => ({
        ...msg,
        content: nextState.final_content,
        think: nextState.thought_log,
        toolSteps: nextState.tool_steps,
        isStreaming: true,
      }));
    });

    try {
      const stream = await streamChatMessage(session.id, userContent);
      touchRecent();
      for await (const event of stream) {
        hadStreamEvent = true;
        if (event.event === 'meta') {
          const meta = parseSseJson<{ run_id?: string }>(event.data);
          if (meta.run_id) {
            updateMessage(assistantId, (msg) => ({ ...msg, runId: meta.run_id }));
          }
        }

        if (event.event === 'delta') {
          const data = parseSseJson<Record<string, unknown>>(event.data);
          const delta = parseDelta(data);
          if (delta) {
            msgState = applyDelta(msgState, delta);
            deltaBatcher.push(msgState);
          }
        }

        if (event.event === 'final') {
          deltaBatcher.flush();
          const data = parseSseJson<ChatMessageResponse>(event.data);
          if (data.status === 'succeeded') {
            updateMessage(assistantId, (msg) => ({
              ...msg,
              id: data.assistant_message.id,
              content: data.assistant_message.content,
              evidence: data.evidence,
              runId: data.run.id,
              isStreaming: false,
            }));
          }
          setLoading(false);
          return;
        }

        if (event.event === 'error') {
          deltaBatcher.flush();
          const err = parseSseJson<{ message?: string }>(event.data);
          throw new Error(err?.message ?? '流式响应失败');
        }
      }

      deltaBatcher.flush();

      // 流式结束，完成消息状态
      msgState = completeMessageState(msgState);
      updateMessage(assistantId, (msg) => ({
        ...msg,
        content: msgState.final_content,
        think: msgState.thought_log,
        toolSteps: msgState.tool_steps,
        isStreaming: false,
      }));
    } catch (e) {
      if (hadStreamEvent) {
        setError(getErrorMessage(e));
        setLoading(false);
        return;
      }
      try {
        await fallbackToJson();
      } catch (fallbackError) {
        setError(getErrorMessage(fallbackError));
      }
    } finally {
      deltaBatcher.flush();
      setLoading(false);
    }
  }, [session, input, loading, loadingSession, upsertSession, updateMessage]);

  const resetSession = useCallback(() => {
    setSession(null);
    setMessages([]);
    setError(null);
  }, []);

  // 知识库选择界面
  if (!session) {
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          minHeight: 'calc(100vh - 64px)',
        }}
      >
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <WelcomeScreen
            title="知识库问答"
            subtitle="选择知识库，开始基于您的文档进行智能问答"
            suggestions={[]}
          />

          <Box sx={{ maxWidth: 800, mx: 'auto', px: 3, width: '100%' }}>
            <Stack spacing={3}>
              <Typography variant="subtitle1" fontWeight={500}>
                选择知识库
              </Typography>

              <KnowledgeBaseSelector
                knowledgeBases={knowledgeBases}
                selectedIds={selectedKbIds}
                onToggle={toggleKb}
                loading={loading || loadingSession || knowledgeBasesQuery.isLoading}
              />

              <Button
                variant="contained"
                onClick={startSession}
                disabled={loadingSession || knowledgeBasesQuery.isLoading || selectedKbIds.length === 0}
                loading={loading || loadingSession}
                sx={{ alignSelf: 'flex-start' }}
              >
                开始对话
              </Button>
            </Stack>
          </Box>
        </Box>

        <ErrorAlert error={mergedError} onClose={handleCloseError} />
      </Box>
    );
  }

  // 对话界面
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 'calc(100vh - 64px)',
      }}
    >
      {/* 顶部栏 */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: { xs: 2, md: 4 },
          py: 1.5,
          position: 'sticky',
          top: 0,
          zIndex: 5,
          bgcolor: (theme) =>
            theme.palette.mode === 'light'
              ? 'rgba(240, 244, 249, 0.72)'
              : 'rgba(30, 31, 32, 0.72)',
          backdropFilter: 'blur(18px)',
          WebkitBackdropFilter: 'blur(18px)',
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <Typography variant="body2" color="text.secondary">
          已选择 {session.selected_kb_ids?.length || 0} 个知识库
        </Typography>
        <Button
          variant="outlined"
          size="small"
          startIcon={<RestartAltIcon />}
          onClick={resetSession}
        >
          重新选择
        </Button>
      </Box>

      {/* 消息区域 */}
      {messages.length === 0 ? (
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <WelcomeScreen
            title="开始提问吧"
            subtitle="基于您选择的知识库，我会为您提供精准的回答"
            suggestions={[]}
          />
        </Box>
      ) : (
        <MessageList messages={messages} loading={loading || loadingSession} />
      )}

      {/* 错误提示 */}
      <ErrorAlert error={mergedError} onClose={handleCloseError} />

      {/* 底部输入区 */}
      <Box
        sx={{
          position: 'sticky',
          bottom: 0,
          p: { xs: 2, md: 3 },
          background: (theme) =>
            `linear-gradient(to top, ${theme.palette.background.default} 0%, rgba(0,0,0,0) 110%)`,
          borderTop: messages.length > 0 ? 1 : 0,
          borderColor: 'divider',
          zIndex: 10,
        }}
      >
        <Box sx={{ maxWidth: 800, mx: 'auto' }}>
          <InputComposer
            value={input}
            onChange={setInput}
            onSend={handleSend}
            disabled={loading || loadingSession}
            loading={loading || loadingSession}
            placeholder="输入你的问题..."
          />
        </Box>
      </Box>
    </Box>
  );
}


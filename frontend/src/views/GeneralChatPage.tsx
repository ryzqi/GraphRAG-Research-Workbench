'use client';

/**
 * 普通代理聊天页面（Gemini 风格重构）
 */
import { useCallback, useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Box, Chip, FormControlLabel, Stack, Switch, Typography } from '@mui/material';
import {
  createChatSession,
  getChatMessages,
  getChatSession,
  resumeToolApproval,
  sendMessage,
  streamChatMessage,
  streamResumeToolApproval,
  type ChatMessageResponse,
  type ChatSession,
} from '../services/chats';
import { HttpError } from '../services/http';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { parseSseJson } from '../lib/sse';
import {
  completeMessageState,
  createMessageState,
} from '../lib/deltaParser';
import {
  applyMessagesEventToState,
  createMessageStateBatcher,
} from '../services/chatStreamDeltas';

import type { ChatMessage } from '../components/chat/MessageList';

import { useRecentHistory } from '../hooks/useRecentHistory';
import { WelcomeScreen } from '../components/chat/WelcomeScreen';
import { InputComposer } from '../components/chat/InputComposer';

const MessageList = dynamic(
  () => import('../components/chat/MessageList').then((mod) => mod.MessageList),
  { ssr: false }
);

const quickPrompts = [
  { label: '总结要点', value: '请帮我总结以下内容：' },
  { label: '生成清单', value: '请把目标拆成可执行的行动清单：' },
  { label: '优化表达', value: '请把下面内容润色成更专业的表达：' },
  { label: '风险与下一步', value: '请列出潜在风险与下一步建议：' },
];

function isPendingClarification(
  response: ChatMessageResponse
): response is Extract<ChatMessageResponse, { status: 'pending_user_clarification' }> {
  return response.status === 'pending_user_clarification';
}

export function GeneralChatPage() {
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
        setAllowExternal(loadedSession.allow_external);
        setMessages(
          history.map((msg) => ({
            id: msg.id,
            role: msg.role === 'assistant' ? 'assistant' : 'user',
            content: msg.content,
          }))
        );
      } catch (e) {
        if (!active) return;
        // Stale/deleted sessionId in URL is possible (e.g., backend reset or old bookmark). Recover by
        // clearing the param so the user can start a new chat.
        if (e instanceof HttpError && e.status === 404) {
          setSession(null);
          setMessages([]);
          setError(null);
          const nextParams = new URLSearchParams(searchParams.toString());
          nextParams.delete('sessionId');
          replaceSearchParams(nextParams);
          return;
        }
        setError(e instanceof Error ? e.message : '加载会话失败');
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
    setSession(null);
    setMessages([]);
    setError(null);
  }, []);

  const handleSend = useCallback(async () => {
    const content = input.trim();
    if (!content || loading || loadingSession || hasPendingApproval) return;

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content,
    };
    const assistantId = `assistant-${Date.now()}`;
    let msgState = createMessageState();

    setMessages((prev) => [
      ...prev,
      userMessage,
      {
        id: assistantId,
        role: 'assistant',
        content: '',
        think: '',
        toolSteps: [],
        isStreaming: true,
        thinkStartTime: Date.now(),
      },
    ]);
    setInput('');
    setLoading(true);
    setError(null);

    let activeSession: ChatSession;
    try {
      activeSession = session ?? (await createSession());
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建会话失败');
      setLoading(false);
      return;
    }

    let recentTouched = false;
    const touchRecent = () => {
      if (recentTouched) return;
      recentTouched = true;
      upsertSession({
        sessionId: activeSession.id,
        title: content.slice(0, 30),
        type: 'general_chat',
        updatedAt: new Date().toISOString(),
      });
    };

    const fallbackToJson = async () => {
      const response: ChatMessageResponse = await sendMessage(activeSession.id, content);
      touchRecent();
      if (response.status === 'pending_tool_approval') {
        updateMessage(assistantId, (msg) => ({
          ...msg,
          content: response.message ?? '需要你确认将要执行的工具调用。',
          runId: response.run.id,
          pendingToolApproval: {
            message: response.message,
            toolCalls: response.pending_tool_calls.map((call) => ({
              tool_name: call.tool_name,
              extension_name: call.extension_name ?? undefined,
            })),
          },
          think: '',
          isStreaming: false,
        }));
        return;
      }
      if (isPendingClarification(response)) {
        throw new Error('普通聊天不支持澄清补充流程');
      }

      updateMessage(assistantId, () => ({
        id: response.assistant_message.id,
        role: 'assistant',
        content: response.assistant_message.content,
        evidence: response.evidence,
        runId: response.run.id,
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
      const stream = await streamChatMessage(activeSession.id, content);
      touchRecent();
      for await (const event of stream) {
        hadStreamEvent = true;
        if (event.event === 'meta') {
          const meta = parseSseJson<{ run_id?: string }>(event.data);
          if (meta.run_id) {
            updateMessage(assistantId, (msg) => ({ ...msg, runId: meta.run_id }));
          }
        }

        if (event.event === 'messages') {
          const data = parseSseJson<Record<string, unknown>>(event.data);
          msgState = applyMessagesEventToState(msgState, data);
          deltaBatcher.push(msgState);
        }

        if (event.event === 'interrupt') {
          deltaBatcher.flush();
          const data = parseSseJson<ChatMessageResponse>(event.data);
          if (data.status === 'pending_tool_approval') {
            updateMessage(assistantId, (msg) => ({
              ...msg,
              content: data.message ?? '需要你确认将要执行的工具调用。',
              runId: data.run.id,
              pendingToolApproval: {
                message: data.message,
                toolCalls: data.pending_tool_calls.map((call) => ({
                  tool_name: call.tool_name,
                  extension_name: call.extension_name ?? undefined,
                })),
              },
              isStreaming: false,
            }));
            setLoading(false);
            return;
          }
          if (isPendingClarification(data)) {
            throw new Error('普通聊天不支持澄清补充流程');
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
          if (isPendingClarification(data)) {
            throw new Error('普通聊天不支持澄清补充流程');
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
        setError(e instanceof Error ? e.message : '发送消息失败');
        setLoading(false);
        return;
      }
      try {
        await fallbackToJson();
      } catch (fallbackError) {
        setError(fallbackError instanceof Error ? fallbackError.message : '发送消息失败');
      }
    } finally {
      deltaBatcher.flush();
      setLoading(false);
    }
  }, [
    input,
    loading,
    loadingSession,
    hasPendingApproval,
    session,
    createSession,
    upsertSession,
    updateMessage,
  ]);

  const handleToolApproval = useCallback(
    async (pendingMessageId: string, runId: string, approved: boolean) => {
      if (!session || loading) return;
      setLoading(true);
      setError(null);

      let msgState = createMessageState();
      updateMessage(pendingMessageId, (msg) => ({
        ...msg,
        content: '',
        think: '',
        toolSteps: [],
        pendingToolApproval: undefined,
        isStreaming: true,
        thinkStartTime: Date.now(),
      }));

      const fallbackToJson = async () => {
        const response: ChatMessageResponse = await resumeToolApproval(session.id, runId, approved);
        if (response.status === 'pending_tool_approval') {
          updateMessage(pendingMessageId, (msg) => ({
            ...msg,
            content: response.message ?? '仍需要审批工具调用。',
            runId: response.run.id,
            pendingToolApproval: {
              message: response.message,
              toolCalls: response.pending_tool_calls.map((call) => ({
                tool_name: call.tool_name,
                extension_name: call.extension_name ?? undefined,
              })),
            },
            think: '',
            isStreaming: false,
          }));
          return;
        }
        if (isPendingClarification(response)) {
          throw new Error('普通聊天不支持澄清补充流程');
        }

        updateMessage(pendingMessageId, () => ({
          id: response.assistant_message.id,
          role: 'assistant' as const,
          content: response.assistant_message.content,
          evidence: response.evidence,
          runId: response.run.id,
          isStreaming: false,
        }));
      };

      let hadStreamEvent = false;
      const deltaBatcher = createMessageStateBatcher((nextState) => {
        updateMessage(pendingMessageId, (msg) => ({
          ...msg,
          content: nextState.final_content,
          think: nextState.thought_log,
          toolSteps: nextState.tool_steps,
          isStreaming: true,
        }));
      });

      try {
        const stream = await streamResumeToolApproval(session.id, runId, approved);
        for await (const event of stream) {
          hadStreamEvent = true;
          if (event.event === 'meta') {
            const meta = parseSseJson<{ run_id?: string }>(event.data);
            if (meta.run_id) {
              updateMessage(pendingMessageId, (msg) => ({ ...msg, runId: meta.run_id }));
            }
          }

          if (event.event === 'messages') {
            const data = parseSseJson<Record<string, unknown>>(event.data);
            msgState = applyMessagesEventToState(msgState, data);
            deltaBatcher.push(msgState);
          }

          if (event.event === 'interrupt') {
            deltaBatcher.flush();
            const data = parseSseJson<ChatMessageResponse>(event.data);
            if (data.status === 'pending_tool_approval') {
              updateMessage(pendingMessageId, (msg) => ({
                ...msg,
                content: data.message ?? '仍需要审批工具调用。',
                runId: data.run.id,
                pendingToolApproval: {
                  message: data.message,
                  toolCalls: data.pending_tool_calls.map((call) => ({
                    tool_name: call.tool_name,
                    extension_name: call.extension_name ?? undefined,
                  })),
                },
                isStreaming: false,
              }));
              setLoading(false);
              return;
            }
            if (isPendingClarification(data)) {
              throw new Error('普通聊天不支持澄清补充流程');
            }
          }

          if (event.event === 'final') {
            deltaBatcher.flush();
            const data = parseSseJson<ChatMessageResponse>(event.data);
            if (data.status === 'succeeded') {
              updateMessage(pendingMessageId, (msg) => ({
                ...msg,
                id: data.assistant_message.id,
                content: data.assistant_message.content,
                evidence: data.evidence,
                runId: data.run.id,
                isStreaming: false,
              }));
            }
            if (isPendingClarification(data)) {
              throw new Error('普通聊天不支持澄清补充流程');
            }
            setLoading(false);
            return;
          }

          if (event.event === 'error') {
            deltaBatcher.flush();
            const err = parseSseJson<{ message?: string }>(event.data);
            throw new Error(err?.message ?? '恢复执行失败');
          }
        }

        deltaBatcher.flush();

        // 流式结束，完成消息状态
        msgState = completeMessageState(msgState);
        updateMessage(pendingMessageId, (msg) => ({
          ...msg,
          content: msgState.final_content,
          think: msgState.thought_log,
          toolSteps: msgState.tool_steps,
          isStreaming: false,
        }));
      } catch (e) {
        if (hadStreamEvent) {
          setError(e instanceof Error ? e.message : '恢复执行失败');
          setLoading(false);
          return;
        }
        try {
          await fallbackToJson();
        } catch (fallbackError) {
          setError(fallbackError instanceof Error ? fallbackError.message : '恢复执行失败');
        }
      } finally {
        deltaBatcher.flush();
        setLoading(false);
      }
    },
    [session, loading, updateMessage]
  );

  const handleSuggestionClick = (value: string) => {
    setInput(value);
  };

  const sessionBadgeLabel = session
    ? session.allow_external
      ? 'MCP 已启用'
      : 'MCP 未启用'
    : allowExternal
      ? 'MCP 将启用'
      : 'MCP 已关闭';
  const webSearchBadgeLabel = webSearchAvailable ? '联网可用' : '联网不可用';

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 'calc(100vh - 64px)',
      }}
    >
      {/* 设置栏 */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: 2,
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
        <FormControlLabel
          control={
            <Switch
              size="small"
              checked={allowExternal}
              onChange={(event) => setAllowExternal(event.target.checked)}
              disabled={!!session}
            />
          }
          label={
            <Typography variant="body2" color="text.secondary">
              MCP 扩展
            </Typography>
          }
        />
        <Chip
          label={webSearchBadgeLabel}
          size="small"
          variant="outlined"
          color={webSearchAvailable ? 'success' : 'default'}
        />
        <Chip label={sessionBadgeLabel} size="small" variant="outlined" />
      </Box>

      {/* 消息区域 */}
      {messages.length === 0 ? (
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <WelcomeScreen
            title="你好，需要我为你做些什么？"
            suggestions={quickPrompts}
            onSuggestionClick={handleSuggestionClick}
            disabled={isInputDisabled}
          />
        </Box>
      ) : (
        <MessageList
          messages={messages}
          loading={loading}
          onToolApprove={(msgId, runId) => handleToolApproval(msgId, runId, true)}
          onToolReject={(msgId, runId) => handleToolApproval(msgId, runId, false)}
          approvalLoading={loading}
        />
      )}

      {/* 错误提示 */}
      <ErrorAlert error={error} onClose={() => setError(null)} />

      {/* 底部输入区 - Sticky 定位 */}
      <Box
        sx={{
          position: 'sticky',
          bottom: 0,
          p: { xs: 2, md: 3 },
          zIndex: 10,
          // Bottom fade to keep the input area readable over long conversations.
          background: (theme) =>
            `linear-gradient(to top, ${theme.palette.background.default} 0%, rgba(0,0,0,0) 110%)`,
        }}
      >
        <Box sx={{ maxWidth: 800, mx: 'auto' }}>
          <InputComposer
            value={input}
            onChange={setInput}
            onSend={handleSend}
            disabled={isInputDisabled}
            loading={loading}
            placeholder={hasPendingApproval ? '等待工具审批完成...' : '输入消息...'}
          />
        </Box>
      </Box>

    </Box>
  );
}

export default GeneralChatPage;

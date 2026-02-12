'use client';

/**
 * 知识库问答页面
 * - 玻璃感知识库选择交互
 * - LangGraph 步骤实时可视化
 * - 澄清补充交互（pending_user_clarification）
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import {
  Box,
  Chip,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import { Button } from '../components/ui/Button';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { KnowledgeBaseSelector } from '../components/KnowledgeBaseSelector';

import type { ChatMessage } from '../components/chat/MessageList';
import type { PipelineStep } from '../components/chat/PipelineProgress';

import {
  type AgentMode,
  type ChatMessageResponse,
  type ChatSession,
  createChatSession,
  getChatMessages,
  getChatSession,
  resumeClarification,
  sendMessage,
  streamChatMessage,
  streamResumeClarification,
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

const PIPELINE_STATUS = ['started', 'completed', 'failed', 'waiting_user', 'skipped'] as const;
type PipelineStatus = (typeof PIPELINE_STATUS)[number];

const PIPELINE_STEP_ORDER: Record<string, number> = {
  preprocess: 0,
  retrieve: 1,
  judge: 2,
  generate: 3,
  verify: 4,
  finalize: 5,
};

function isPipelineStatus(value: unknown): value is PipelineStatus {
  return typeof value === 'string' && (PIPELINE_STATUS as readonly string[]).includes(value);
}

function sortPipelineSteps(steps: PipelineStep[]): PipelineStep[] {
  return [...steps].sort((a, b) => {
    const orderA = PIPELINE_STEP_ORDER[a.step_id] ?? Number.MAX_SAFE_INTEGER;
    const orderB = PIPELINE_STEP_ORDER[b.step_id] ?? Number.MAX_SAFE_INTEGER;
    if (orderA !== orderB) {
      return orderA - orderB;
    }
    return (a.ts ?? '').localeCompare(b.ts ?? '');
  });
}

function upsertPipelineStep(
  steps: PipelineStep[] | undefined,
  incoming: PipelineStep
): PipelineStep[] {
  const current = [...(steps ?? [])];
  const index = current.findIndex((step) => step.step_id === incoming.step_id);
  if (index === -1) {
    current.push(incoming);
  } else {
    current[index] = {
      ...current[index],
      ...incoming,
      label: incoming.label || current[index].label,
    };
  }
  return sortPipelineSteps(current);
}

function finalizePipelineSteps(steps: PipelineStep[] | undefined): PipelineStep[] | undefined {
  if (!steps || steps.length === 0) {
    return steps;
  }
  return steps.map((step) => {
    if (step.status === 'started') {
      return { ...step, status: 'completed' };
    }
    return step;
  });
}

function parseStepEvent(data: Record<string, unknown>): PipelineStep | null {
  const stepId = typeof data.step_id === 'string' ? data.step_id : '';
  const status = isPipelineStatus(data.status) ? data.status : null;
  if (!stepId || !status) {
    return null;
  }
  return {
    step_id: stepId,
    label: typeof data.label === 'string' ? data.label : stepId,
    status,
    node: typeof data.node === 'string' ? data.node : undefined,
    message: typeof data.message === 'string' ? data.message : undefined,
    ts: typeof data.ts === 'string' ? data.ts : new Date().toISOString(),
    meta: data.meta && typeof data.meta === 'object' ? (data.meta as Record<string, unknown>) : undefined,
  };
}

function isPendingClarificationResponse(
  response: ChatMessageResponse
): response is Extract<ChatMessageResponse, { status: 'pending_user_clarification' }> {
  return response.status === 'pending_user_clarification';
}

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
  const knowledgeBases = knowledgeBasesQuery.data;

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

  const selectedKbNames = useMemo(() => {
    const map = new Map((knowledgeBases ?? []).map((kb) => [kb.id, kb.name]));
    return selectedKbIds.map((id) => map.get(id) ?? id);
  }, [knowledgeBases, selectedKbIds]);

  const hasPendingClarification = useMemo(
    () => messages.some((msg) => Boolean(msg.pendingClarification)),
    [messages]
  );

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    let active = true;
    const loadSession = async () => {
      setLoadingSession(true);
      setError(null);
      try {
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

  const applyStepEvent = useCallback(
    (messageId: string, raw: Record<string, unknown>) => {
      const step = parseStepEvent(raw);
      if (!step) {
        return;
      }
      updateMessage(messageId, (msg) => ({
        ...msg,
        pipelineSteps: upsertPipelineStep(msg.pipelineSteps, step),
      }));
    },
    [updateMessage]
  );

  const markClarificationPending = useCallback(
    (messageId: string, runId: string, message: string) => {
      updateMessage(messageId, (msg) => ({
        ...msg,
        content: '',
        think: '',
        runId,
        pendingClarification: { message },
        pipelineSteps: upsertPipelineStep(msg.pipelineSteps, {
          step_id: 'finalize',
          label: '输出结果',
          status: 'waiting_user',
          message,
          ts: new Date().toISOString(),
        }),
        isStreaming: false,
      }));
    },
    [updateMessage]
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
    if (!session || !input.trim() || loading || loadingSession || hasPendingClarification) return;

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
      {
        id: assistantId,
        role: 'assistant',
        content: '',
        think: '',
        toolSteps: [],
        pipelineSteps: [],
        isStreaming: true,
        thinkStartTime: Date.now(),
      },
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
      touchRecent();
      if (isPendingClarificationResponse(response)) {
        markClarificationPending(assistantId, response.run.id, response.message);
        return;
      }
      if (response.status !== 'succeeded') {
        throw new Error('知识库对话返回了不支持的中间状态');
      }
      updateMessage(assistantId, (msg) => ({
        ...msg,
        id: response.assistant_message.id,
        role: 'assistant',
        content: response.assistant_message.content,
        evidence: response.evidence,
        runId: response.run.id,
        pipelineSteps: finalizePipelineSteps(msg.pipelineSteps),
        pendingClarification: undefined,
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

        if (event.event === 'step') {
          applyStepEvent(assistantId, parseSseJson<Record<string, unknown>>(event.data));
        }

        if (event.event === 'delta') {
          const data = parseSseJson<Record<string, unknown>>(event.data);
          const delta = parseDelta(data);
          if (delta) {
            msgState = applyDelta(msgState, delta);
            deltaBatcher.push(msgState);
          }
        }

        if (event.event === 'interrupt') {
          deltaBatcher.flush();
          const data = parseSseJson<ChatMessageResponse>(event.data);
          if (isPendingClarificationResponse(data)) {
            markClarificationPending(assistantId, data.run.id, data.message);
            setLoading(false);
            return;
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
              pipelineSteps: finalizePipelineSteps(msg.pipelineSteps),
              pendingClarification: undefined,
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
      msgState = completeMessageState(msgState);
      updateMessage(assistantId, (msg) => ({
        ...msg,
        content: msgState.final_content,
        think: msgState.thought_log,
        toolSteps: msgState.tool_steps,
        pipelineSteps: finalizePipelineSteps(msg.pipelineSteps),
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
  }, [
    session,
    input,
    loading,
    loadingSession,
    hasPendingClarification,
    upsertSession,
    updateMessage,
    applyStepEvent,
    markClarificationPending,
  ]);

  const handleClarificationSubmit = useCallback(
    async (messageId: string, runId: string, content: string) => {
      if (!session || loading || loadingSession) return;

      setLoading(true);
      setError(null);
      let msgState = createMessageState();
      updateMessage(messageId, (msg) => ({
        ...msg,
        content: '',
        think: '',
        pendingClarification: undefined,
        pipelineSteps: upsertPipelineStep(msg.pipelineSteps, {
          step_id: 'finalize',
          label: '输出结果',
          status: 'started',
          message: '已收到补充信息，继续执行',
          ts: new Date().toISOString(),
        }),
        isStreaming: true,
        thinkStartTime: Date.now(),
      }));

      const fallbackToJson = async () => {
        const response = await resumeClarification(session.id, runId, content);
        if (isPendingClarificationResponse(response)) {
          markClarificationPending(messageId, response.run.id, response.message);
          return;
        }
        if (response.status !== 'succeeded') {
          throw new Error('恢复执行返回了不支持的状态');
        }
        updateMessage(messageId, (msg) => ({
          ...msg,
          id: response.assistant_message.id,
          content: response.assistant_message.content,
          evidence: response.evidence,
          runId: response.run.id,
          pendingClarification: undefined,
          pipelineSteps: finalizePipelineSteps(msg.pipelineSteps),
          isStreaming: false,
        }));
      };

      let hadStreamEvent = false;
      const deltaBatcher = createMessageStateBatcher((nextState) => {
        updateMessage(messageId, (msg) => ({
          ...msg,
          content: nextState.final_content,
          think: nextState.thought_log,
          toolSteps: nextState.tool_steps,
          isStreaming: true,
        }));
      });

      try {
        const stream = await streamResumeClarification(session.id, runId, content);
        for await (const event of stream) {
          hadStreamEvent = true;
          if (event.event === 'meta') {
            const meta = parseSseJson<{ run_id?: string }>(event.data);
            if (meta.run_id) {
              updateMessage(messageId, (msg) => ({ ...msg, runId: meta.run_id }));
            }
          }

          if (event.event === 'step') {
            applyStepEvent(messageId, parseSseJson<Record<string, unknown>>(event.data));
          }

          if (event.event === 'delta') {
            const data = parseSseJson<Record<string, unknown>>(event.data);
            const delta = parseDelta(data);
            if (delta) {
              msgState = applyDelta(msgState, delta);
              deltaBatcher.push(msgState);
            }
          }

          if (event.event === 'interrupt') {
            deltaBatcher.flush();
            const data = parseSseJson<ChatMessageResponse>(event.data);
            if (isPendingClarificationResponse(data)) {
              markClarificationPending(messageId, data.run.id, data.message);
              setLoading(false);
              return;
            }
          }

          if (event.event === 'final') {
            deltaBatcher.flush();
            const data = parseSseJson<ChatMessageResponse>(event.data);
            if (data.status === 'succeeded') {
              updateMessage(messageId, (msg) => ({
                ...msg,
                id: data.assistant_message.id,
                content: data.assistant_message.content,
                evidence: data.evidence,
                runId: data.run.id,
                pendingClarification: undefined,
                pipelineSteps: finalizePipelineSteps(msg.pipelineSteps),
                isStreaming: false,
              }));
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
        msgState = completeMessageState(msgState);
        updateMessage(messageId, (msg) => ({
          ...msg,
          content: msgState.final_content,
          think: msgState.thought_log,
          toolSteps: msgState.tool_steps,
          pipelineSteps: finalizePipelineSteps(msg.pipelineSteps),
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
    },
    [
      session,
      loading,
      loadingSession,
      updateMessage,
      applyStepEvent,
      markClarificationPending,
    ]
  );

  const resetSession = useCallback(() => {
    setSession(null);
    setMessages([]);
    setError(null);
  }, []);

  if (!session) {
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          minHeight: 'calc(100vh - 64px)',
          background:
            'radial-gradient(circle at 10% 0%, rgba(66,133,244,0.16), transparent 40%), radial-gradient(circle at 100% 10%, rgba(155,114,203,0.12), transparent 35%)',
        }}
      >
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <WelcomeScreen title="知识库问答" suggestions={[]} />

          <Box sx={{ maxWidth: 860, mx: 'auto', px: 3, width: '100%' }}>
            <Paper
              variant="outlined"
              sx={{
                p: { xs: 2.5, md: 3 },
                borderRadius: 4,
                bgcolor: (theme) =>
                  theme.palette.mode === 'light'
                    ? alpha(theme.palette.common.white, 0.72)
                    : alpha(theme.palette.background.paper, 0.58),
                backdropFilter: 'blur(14px)',
                WebkitBackdropFilter: 'blur(14px)',
                borderColor: (theme) => alpha(theme.palette.primary.main, 0.18),
                boxShadow: (theme) =>
                  `0 18px 40px ${alpha(
                    theme.palette.mode === 'light' ? theme.palette.primary.main : theme.palette.common.black,
                    theme.palette.mode === 'light' ? 0.14 : 0.34
                  )}`,
              }}
            >
              <Stack spacing={2.5}>
                <Stack direction="row" alignItems="center" spacing={1}>
                  <AutoAwesomeIcon color="primary" fontSize="small" />
                  <Typography variant="subtitle1" fontWeight={600}>
                    选择知识库范围
                  </Typography>
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  支持多库联合检索。建议优先选择最相关的 1-3 个知识库，提升命中率与响应速度。
                </Typography>

                <KnowledgeBaseSelector
                  knowledgeBases={knowledgeBases ?? []}
                  selectedIds={selectedKbIds}
                  onToggle={toggleKb}
                  loading={loading || loadingSession || knowledgeBasesQuery.isLoading}
                />

                {selectedKbNames.length > 0 && (
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    {selectedKbNames.slice(0, 5).map((name) => (
                      <Chip key={name} label={name} size="small" color="primary" variant="outlined" />
                    ))}
                    {selectedKbNames.length > 5 && (
                      <Chip label={`+${selectedKbNames.length - 5}`} size="small" variant="outlined" />
                    )}
                  </Stack>
                )}

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
            </Paper>
          </Box>
        </Box>

        <ErrorAlert error={mergedError} onClose={handleCloseError} />
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 'calc(100vh - 64px)',
      }}
    >
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
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="body2" color="text.secondary">
            已选择 {session.selected_kb_ids?.length || 0} 个知识库
          </Typography>
          {hasPendingClarification && (
            <Chip size="small" color="warning" label="等待补充信息" />
          )}
        </Stack>
        <Button
          variant="outlined"
          size="small"
          startIcon={<RestartAltIcon />}
          onClick={resetSession}
        >
          重新选择
        </Button>
      </Box>

      {messages.length === 0 ? (
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <WelcomeScreen title="开始提问吧" suggestions={[]} />
        </Box>
      ) : (
        <MessageList
          messages={messages}
          loading={loading || loadingSession}
          onClarificationSubmit={handleClarificationSubmit}
          approvalLoading={loading || loadingSession}
        />
      )}

      <ErrorAlert error={mergedError} onClose={handleCloseError} />

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
            disabled={loading || loadingSession || hasPendingClarification}
            loading={loading || loadingSession}
            placeholder={hasPendingClarification ? '请先补充上方澄清信息...' : '输入你的问题...'}
          />
        </Box>
      </Box>
    </Box>
  );
}

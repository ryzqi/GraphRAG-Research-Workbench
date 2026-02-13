'use client';

/**
 * 知识库问答页面
 * - 玻璃感知识库选择交互
 * - LangGraph 步骤实时可视化
 * - 澄清补充交互（pending_user_clarification）
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { KbChatConfigPanel } from '../components/chat/KbChatConfigPanel';

import type { ChatMessage } from '../components/chat/MessageList';
import type {
  PipelineStep,
  PipelineTimelineEvent,
} from '../components/chat/PipelineProgress';

import {
  type AgentRunStatus,
  type AgentMode,
  type ChatRunStateEvent,
  type ChatRunUiEvent,
  type KbChatConfig,
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
const RUN_STREAM_STATUS = ['running', 'succeeded', 'failed', 'canceled', 'waiting_user'] as const;
type RunStreamStatus = (typeof RUN_STREAM_STATUS)[number];
type TerminalRunStatus = Exclude<RunStreamStatus, 'running'>;

const PIPELINE_STEP_ORDER: Record<string, number> = {
  merge_context: 0,
  coref_rewrite: 1,
  ambiguity_check: 2,
  normalize_rewrite: 3,
  decomposition: 4,
  multi_query_check: 5,
  generate_variants: 6,
  entity_expand: 7,
  hyde_check: 8,
  hyde: 9,
  prepare_messages: 10,
  retrieve: 11,
  doc_grader: 12,
  transform_query: 13,
  generate: 14,
  generate_strict: 15,
  hallucination_check: 16,
  answer_check: 17,
  finalize: 18,
  force_exit: 19,
};

const DEFAULT_KB_CHAT_CONFIG: KbChatConfig = {
  query_rewrite_enabled: true,
  ambiguity_check_enabled: true,
  decomposition_enabled: false,
  multi_query_enabled: false,
  hyde_enabled: false,
  hybrid_retrieval_enabled: true,
  rerank_enabled: true,
  force_retrieve_enabled: true,
};

const KB_CHAT_CONFIG_LABELS: Record<keyof KbChatConfig, string> = {
  query_rewrite_enabled: '查询改写',
  ambiguity_check_enabled: '歧义检测',
  decomposition_enabled: '问题分解',
  multi_query_enabled: '多路查询',
  hyde_enabled: 'HyDE',
  hybrid_retrieval_enabled: '混合检索',
  rerank_enabled: '重排序',
  force_retrieve_enabled: '强制检索',
};

function isPipelineStatus(value: unknown): value is PipelineStatus {
  return typeof value === 'string' && (PIPELINE_STATUS as readonly string[]).includes(value);
}

function isRunStreamStatus(value: unknown): value is RunStreamStatus {
  return typeof value === 'string' && (RUN_STREAM_STATUS as readonly string[]).includes(value);
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

function calculateProgress(steps: PipelineStep[] | undefined) {
  const stepList = steps ?? [];
  const total = Math.max(stepList.length, 1);
  const completed = stepList.filter(
    (step) =>
      step.status === 'completed' ||
      step.status === 'skipped' ||
      step.status === 'failed' ||
      step.status === 'waiting_user'
  ).length;
  const percent = total > 0 ? Math.min(100, Math.round((completed / total) * 1000) / 10) : 0;
  return { completed, total, percent };
}

function createInitialRunState(runId: string): ChatRunStateEvent {
  return {
    run_id: runId,
    run_status: 'running',
    current_step_id: null,
    current_step_label: null,
    current_step_status: null,
    current_node: null,
    attempt: null,
    message: null,
    progress: {
      completed: 0,
      total: Object.keys(PIPELINE_STEP_ORDER).length,
      percent: 0,
    },
    ts: new Date().toISOString(),
  };
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

function parseStateEvent(data: Record<string, unknown>): ChatRunStateEvent | null {
  const runId = typeof data.run_id === 'string' ? data.run_id : '';
  const runStatus = isRunStreamStatus(data.run_status) ? data.run_status : null;
  if (!runId || !runStatus) {
    return null;
  }
  const progressRaw =
    data.progress && typeof data.progress === 'object'
      ? (data.progress as Record<string, unknown>)
      : {};
  const completed =
    typeof progressRaw.completed === 'number' ? progressRaw.completed : 0;
  const total =
    typeof progressRaw.total === 'number'
      ? progressRaw.total
      : Object.keys(PIPELINE_STEP_ORDER).length;
  const percent =
    typeof progressRaw.percent === 'number'
      ? progressRaw.percent
      : total > 0
        ? Math.min(100, Math.round((completed / total) * 1000) / 10)
        : 0;
  return {
    run_id: runId,
    run_status: runStatus,
    current_step_id: typeof data.current_step_id === 'string' ? data.current_step_id : null,
    current_step_label: typeof data.current_step_label === 'string' ? data.current_step_label : null,
    current_step_status: typeof data.current_step_status === 'string' ? data.current_step_status : null,
    current_node: typeof data.current_node === 'string' ? data.current_node : null,
    attempt: typeof data.attempt === 'number' ? data.attempt : null,
    message: typeof data.message === 'string' ? data.message : null,
    state_version: typeof data.state_version === 'number' ? data.state_version : undefined,
    active_path: Array.isArray(data.active_path)
      ? data.active_path.filter((item): item is string => typeof item === 'string')
      : undefined,
    last_good_answer:
      typeof data.last_good_answer === 'string' ? data.last_good_answer : undefined,
    degrade_reason: typeof data.degrade_reason === 'string' ? data.degrade_reason : undefined,
    progress: { completed, total, percent },
    ts: typeof data.ts === 'string' ? data.ts : new Date().toISOString(),
  };
}

function parseUiEvent(data: Record<string, unknown>): ChatRunUiEvent | null {
  const runId = typeof data.run_id === 'string' ? data.run_id : '';
  const eventType = typeof data.event_type === 'string' ? data.event_type : '';
  if (!runId || !eventType) {
    return null;
  }
  return {
    event_type: eventType,
    run_id: runId,
    step_id: typeof data.step_id === 'string' ? data.step_id : null,
    status: typeof data.status === 'string' ? data.status : null,
    node: typeof data.node === 'string' ? data.node : null,
    message: typeof data.message === 'string' ? data.message : null,
    candidate_answer:
      typeof data.candidate_answer === 'string' ? data.candidate_answer : null,
    source_step_id:
      typeof data.source_step_id === 'string' ? data.source_step_id : null,
    degrade_reason:
      typeof data.degrade_reason === 'string' ? data.degrade_reason : null,
    meta:
      data.meta && typeof data.meta === 'object'
        ? (data.meta as Record<string, unknown>)
        : null,
    ts: typeof data.ts === 'string' ? data.ts : new Date().toISOString(),
  };
}

function createTimelineEventFromStep(step: PipelineStep): PipelineTimelineEvent {
  const attempt = typeof step.meta?.attempt === 'number' ? step.meta.attempt : null;
  const ioSummaryRaw = step.meta?.io_summary;
  const ioSummary =
    ioSummaryRaw && typeof ioSummaryRaw === 'object'
      ? (ioSummaryRaw as Record<string, unknown>)
      : null;
  return {
    id: `step-${step.step_id}-${step.status}-${step.ts ?? Date.now()}`,
    source: 'step',
    step_id: step.step_id,
    label: step.label,
    node: step.node ?? null,
    status: step.status,
    run_status: null,
    attempt,
    message: step.message ?? null,
    io_summary: ioSummary,
    ts: step.ts ?? new Date().toISOString(),
  };
}

function createTimelineEventFromState(state: ChatRunStateEvent): PipelineTimelineEvent {
  return {
    id: `state-${state.run_id}-${state.state_version ?? state.ts}`,
    source: 'state',
    step_id: state.current_step_id,
    label: state.current_step_label ?? state.current_node ?? '执行状态',
    node: state.current_node,
    status: state.current_step_status ?? state.run_status,
    run_status: state.run_status,
    attempt: state.attempt,
    message: state.message,
    event_type: 'state',
    ts: state.ts,
  };
}

function createTimelineEventFromUi(event: ChatRunUiEvent): PipelineTimelineEvent {
  const label =
    event.event_type === 'degraded_to_candidate'
      ? '降级候选答案'
      : event.event_type === 'candidate_answer_updated'
        ? '候选答案更新'
        : event.step_id ?? event.event_type;
  return {
    id: `ui-${event.run_id}-${event.event_type}-${event.ts}`,
    source: 'ui',
    step_id: event.step_id ?? null,
    label,
    node: event.node ?? null,
    status: event.status ?? 'running',
    run_status: null,
    attempt:
      typeof event.meta?.attempt === 'number' ? (event.meta.attempt as number) : null,
    message: event.message ?? null,
    event_type: event.event_type,
    ts: event.ts,
  };
}

function appendTimelineEvent(
  timeline: PipelineTimelineEvent[] | undefined,
  event: PipelineTimelineEvent
): PipelineTimelineEvent[] {
  const current = timeline ?? [];
  const last = current[current.length - 1];
  const lastSummary = last?.io_summary ? JSON.stringify(last.io_summary) : '';
  const nextSummary = event.io_summary ? JSON.stringify(event.io_summary) : '';
  if (
    last &&
    last.source === event.source &&
    last.step_id === event.step_id &&
    last.node === event.node &&
    last.status === event.status &&
    last.run_status === event.run_status &&
    last.event_type === event.event_type &&
    last.attempt === event.attempt &&
    last.message === event.message &&
    lastSummary === nextSummary
  ) {
    return current;
  }
  return [...current, event];
}

function createTerminalRunState(
  runId: string,
  status: TerminalRunStatus,
  steps: PipelineStep[] | undefined,
  message?: string,
  previousState?: ChatRunStateEvent
): ChatRunStateEvent {
  const sorted = sortPipelineSteps(steps ?? []);
  const current = sorted[sorted.length - 1];
  return {
    run_id: runId,
    run_status: status,
    current_step_id: current?.step_id ?? (status === 'waiting_user' ? 'finalize' : null),
    current_step_label: current?.label ?? (status === 'waiting_user' ? '输出结果' : null),
    current_step_status: current?.status ?? (status === 'waiting_user' ? 'waiting_user' : null),
    current_node: current?.node ?? null,
    attempt: typeof current?.meta?.attempt === 'number' ? current.meta.attempt : null,
    message: message ?? current?.message ?? null,
    state_version: previousState?.state_version,
    active_path: previousState?.active_path,
    last_good_answer: previousState?.last_good_answer,
    degrade_reason: previousState?.degrade_reason,
    progress: calculateProgress(sorted),
    ts: new Date().toISOString(),
  };
}

function resolveTerminalRunStatus(
  status: AgentRunStatus | RunStreamStatus | undefined,
  fallback: TerminalRunStatus = 'succeeded'
): TerminalRunStatus {
  if (!status || !isRunStreamStatus(status)) {
    return fallback;
  }
  if (status === 'running') {
    return fallback;
  }
  return status;
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
  const [kbChatConfig, setKbChatConfig] = useState<KbChatConfig>(DEFAULT_KB_CHAT_CONFIG);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const composerRef = useRef<HTMLDivElement | null>(null);
  const [bottomInset, setBottomInset] = useState(220);

  const { upsertSession } = useRecentHistory();

  const mergedError =
    error ?? (knowledgeBasesQuery.error ? getErrorMessage(knowledgeBasesQuery.error) : null);

  const selectedKbNames = useMemo(() => {
    const map = new Map((knowledgeBases ?? []).map((kb) => [kb.id, kb.name]));
    return selectedKbIds.map((id) => map.get(id) ?? id);
  }, [knowledgeBases, selectedKbIds]);

  const activeConfig = session?.kb_chat_config ?? kbChatConfig;
  const enabledConfigLabels = useMemo(
    () =>
      (Object.keys(KB_CHAT_CONFIG_LABELS) as Array<keyof KbChatConfig>)
        .filter((key) => Boolean(activeConfig[key]))
        .map((key) => KB_CHAT_CONFIG_LABELS[key]),
    [activeConfig]
  );

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
        setKbChatConfig(loadedSession.kb_chat_config ?? DEFAULT_KB_CHAT_CONFIG);
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
          setKbChatConfig(DEFAULT_KB_CHAT_CONFIG);
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
    setKbChatConfig(DEFAULT_KB_CHAT_CONFIG);
  }, [sessionId]);

  useEffect(() => {
    const element = composerRef.current;
    if (!element) {
      return;
    }

    const updateInset = () => {
      const next = Math.max(180, Math.ceil(element.getBoundingClientRect().height) + 24);
      setBottomInset(next);
    };

    updateInset();
    if (typeof ResizeObserver === 'undefined') {
      return;
    }
    const observer = new ResizeObserver(updateInset);
    observer.observe(element);
    return () => observer.disconnect();
  }, [session, hasPendingClarification]);

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
        nodeTimeline: appendTimelineEvent(
          msg.nodeTimeline,
          createTimelineEventFromStep(step)
        ),
      }));
    },
    [updateMessage]
  );

  const applyStateEvent = useCallback(
    (messageId: string, raw: Record<string, unknown>) => {
      const state = parseStateEvent(raw);
      if (!state) {
        return;
      }
      updateMessage(messageId, (msg) => {
        const nextTimeline = appendTimelineEvent(
          msg.nodeTimeline,
          createTimelineEventFromState(state)
        );
        const nextRunState = {
          ...(msg.runState ?? createInitialRunState(state.run_id)),
          ...state,
          last_good_answer:
            state.last_good_answer ?? msg.runState?.last_good_answer ?? null,
          degrade_reason: state.degrade_reason ?? msg.runState?.degrade_reason ?? null,
        };
        const shouldUseCandidateFallback =
          nextRunState.run_status === 'failed' &&
          (!msg.content || !msg.content.trim()) &&
          typeof nextRunState.last_good_answer === 'string' &&
          nextRunState.last_good_answer.trim().length > 0;
        return {
          ...msg,
          runId: state.run_id,
          runState: nextRunState,
          nodeTimeline: nextTimeline,
          content: shouldUseCandidateFallback
            ? nextRunState.last_good_answer ?? msg.content
            : msg.content,
        };
      });
    },
    [updateMessage]
  );

  const applyUiEvent = useCallback(
    (messageId: string, raw: Record<string, unknown>) => {
      const uiEvent = parseUiEvent(raw);
      if (!uiEvent) {
        return;
      }
      updateMessage(messageId, (msg) => {
        const nextTimeline = appendTimelineEvent(
          msg.nodeTimeline,
          createTimelineEventFromUi(uiEvent)
        );
        const baseRunState =
          msg.runState ??
          (msg.runId ? createInitialRunState(msg.runId) : createInitialRunState(uiEvent.run_id));
        const nextRunState = {
          ...baseRunState,
          run_id: uiEvent.run_id,
          last_good_answer:
            uiEvent.candidate_answer ?? baseRunState.last_good_answer ?? null,
          degrade_reason: uiEvent.degrade_reason ?? baseRunState.degrade_reason ?? null,
          message: uiEvent.message ?? baseRunState.message,
          ts: uiEvent.ts,
        };
        const shouldUseCandidateFallback =
          uiEvent.event_type === 'degraded_to_candidate' &&
          (!msg.content || !msg.content.trim()) &&
          typeof nextRunState.last_good_answer === 'string' &&
          nextRunState.last_good_answer.trim().length > 0;
        return {
          ...msg,
          runId: uiEvent.run_id,
          runState: nextRunState,
          nodeTimeline: nextTimeline,
          content: shouldUseCandidateFallback
            ? nextRunState.last_good_answer ?? msg.content
            : msg.content,
        };
      });
    },
    [updateMessage]
  );

  const markClarificationPending = useCallback(
    (messageId: string, runId: string, message: string) => {
      updateMessage(messageId, (msg) => {
        const nextSteps = upsertPipelineStep(msg.pipelineSteps, {
          step_id: 'finalize',
          label: '输出结果',
          status: 'waiting_user',
          message,
          ts: new Date().toISOString(),
        });
        const nextRunState = createTerminalRunState(
          runId,
          'waiting_user',
          nextSteps,
          message,
          msg.runState
        );
        return {
          ...msg,
          content: '',
          think: '',
          runId,
          pendingClarification: { message },
          pipelineSteps: nextSteps,
          runState: nextRunState,
          isStreaming: false,
        };
      });
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
        kb_chat_config: kbChatConfig,
      });
      setSession(newSession);
      setKbChatConfig(newSession.kb_chat_config ?? kbChatConfig);
      setMessages([]);
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [selectedKbIds, kbChatConfig]);

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
        nodeTimeline: [],
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
      updateMessage(assistantId, (msg) => {
        const nextSteps = finalizePipelineSteps(msg.pipelineSteps);
        const nextRunState = createTerminalRunState(
          response.run.id,
          resolveTerminalRunStatus(response.run.status),
          nextSteps,
          undefined,
          msg.runState
        );
        return {
          ...msg,
          id: response.assistant_message.id,
          role: 'assistant',
          content: response.assistant_message.content,
          evidence: response.evidence,
          runId: response.run.id,
          pipelineSteps: nextSteps,
          runState: nextRunState,
          pendingClarification: undefined,
          isStreaming: false,
        };
      });
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
          const runIdFromMeta = meta.run_id;
          if (runIdFromMeta) {
            updateMessage(assistantId, (msg) => {
              const nextRunState = msg.runState ?? createInitialRunState(runIdFromMeta);
              return {
                ...msg,
                runId: runIdFromMeta,
                runState: nextRunState,
              };
            });
          }
        }

        if (event.event === 'step') {
          applyStepEvent(assistantId, parseSseJson<Record<string, unknown>>(event.data));
        }

        if (event.event === 'state') {
          applyStateEvent(assistantId, parseSseJson<Record<string, unknown>>(event.data));
        }

        if (event.event === 'ui_event') {
          applyUiEvent(assistantId, parseSseJson<Record<string, unknown>>(event.data));
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
            updateMessage(assistantId, (msg) => {
              const nextSteps = finalizePipelineSteps(msg.pipelineSteps);
              const nextRunState = createTerminalRunState(
                data.run.id,
                resolveTerminalRunStatus(
                  data.run.status,
                  resolveTerminalRunStatus(msg.runState?.run_status)
                ),
                nextSteps,
                undefined,
                msg.runState
              );
              return {
                ...msg,
                id: data.assistant_message.id,
                content: data.assistant_message.content,
                evidence: data.evidence,
                runId: data.run.id,
                pipelineSteps: nextSteps,
                runState: nextRunState,
                pendingClarification: undefined,
                isStreaming: false,
              };
            });
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
      updateMessage(assistantId, (msg) => {
        const nextSteps = finalizePipelineSteps(msg.pipelineSteps);
        const nextRunState = msg.runId
          ? createTerminalRunState(
              msg.runId,
              resolveTerminalRunStatus(msg.runState?.run_status),
              nextSteps,
              undefined,
              msg.runState
            )
          : msg.runState;
        return {
          ...msg,
          content: msgState.final_content,
          think: msgState.thought_log,
          toolSteps: msgState.tool_steps,
          pipelineSteps: nextSteps,
          runState: nextRunState,
          isStreaming: false,
        };
      });
    } catch (e) {
      if (hadStreamEvent) {
        updateMessage(assistantId, (msg) => {
          const nextRunState = msg.runId
            ? createTerminalRunState(
                msg.runId,
                'failed',
                msg.pipelineSteps,
                getErrorMessage(e),
                msg.runState
              )
            : msg.runState;
          return {
            ...msg,
            isStreaming: false,
            runState: nextRunState,
          };
        });
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
    applyStateEvent,
    applyUiEvent,
    markClarificationPending,
  ]);

  const handleClarificationSubmit = useCallback(
    async (messageId: string, runId: string, content: string) => {
      if (!session || loading || loadingSession) return;

      setLoading(true);
      setError(null);
      let msgState = createMessageState();
      updateMessage(messageId, (msg) => {
        const nextSteps = upsertPipelineStep(msg.pipelineSteps, {
          step_id: 'finalize',
          label: '输出结果',
          status: 'started',
          message: '已收到补充信息，继续执行',
          ts: new Date().toISOString(),
        });
        const startedStep = nextSteps.find((step) => step.step_id === 'finalize');
        return {
          ...msg,
          content: '',
          think: '',
          pendingClarification: undefined,
          pipelineSteps: nextSteps,
          nodeTimeline: startedStep
            ? appendTimelineEvent(
                msg.nodeTimeline,
                createTimelineEventFromStep(startedStep)
              )
            : msg.nodeTimeline,
          isStreaming: true,
          thinkStartTime: Date.now(),
        };
      });

      const fallbackToJson = async () => {
        const response = await resumeClarification(session.id, runId, content);
        if (isPendingClarificationResponse(response)) {
          markClarificationPending(messageId, response.run.id, response.message);
          return;
        }
        if (response.status !== 'succeeded') {
          throw new Error('恢复执行返回了不支持的状态');
        }
        updateMessage(messageId, (msg) => {
          const nextSteps = finalizePipelineSteps(msg.pipelineSteps);
          const nextRunState = createTerminalRunState(
            response.run.id,
            resolveTerminalRunStatus(response.run.status),
            nextSteps,
            undefined,
            msg.runState
          );
          return {
            ...msg,
            id: response.assistant_message.id,
            content: response.assistant_message.content,
            evidence: response.evidence,
            runId: response.run.id,
            pendingClarification: undefined,
            pipelineSteps: nextSteps,
            runState: nextRunState,
            isStreaming: false,
          };
        });
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
            const runIdFromMeta = meta.run_id;
            if (runIdFromMeta) {
              updateMessage(messageId, (msg) => {
                const nextRunState = msg.runState ?? createInitialRunState(runIdFromMeta);
                return {
                  ...msg,
                  runId: runIdFromMeta,
                  runState: nextRunState,
                };
              });
            }
          }

          if (event.event === 'step') {
            applyStepEvent(messageId, parseSseJson<Record<string, unknown>>(event.data));
          }

          if (event.event === 'state') {
            applyStateEvent(messageId, parseSseJson<Record<string, unknown>>(event.data));
          }

          if (event.event === 'ui_event') {
            applyUiEvent(messageId, parseSseJson<Record<string, unknown>>(event.data));
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
              updateMessage(messageId, (msg) => {
                const nextSteps = finalizePipelineSteps(msg.pipelineSteps);
                const nextRunState = createTerminalRunState(
                  data.run.id,
                  resolveTerminalRunStatus(
                    data.run.status,
                    resolveTerminalRunStatus(msg.runState?.run_status)
                  ),
                  nextSteps,
                  undefined,
                  msg.runState
                );
                return {
                  ...msg,
                  id: data.assistant_message.id,
                  content: data.assistant_message.content,
                  evidence: data.evidence,
                  runId: data.run.id,
                  pendingClarification: undefined,
                  pipelineSteps: nextSteps,
                  runState: nextRunState,
                  isStreaming: false,
                };
              });
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
        updateMessage(messageId, (msg) => {
          const nextSteps = finalizePipelineSteps(msg.pipelineSteps);
          const nextRunState = msg.runId
            ? createTerminalRunState(
                msg.runId,
                resolveTerminalRunStatus(msg.runState?.run_status),
                nextSteps,
                undefined,
                msg.runState
              )
            : msg.runState;
          return {
            ...msg,
            content: msgState.final_content,
            think: msgState.thought_log,
            toolSteps: msgState.tool_steps,
            pipelineSteps: nextSteps,
            runState: nextRunState,
            isStreaming: false,
          };
        });
      } catch (e) {
        if (hadStreamEvent) {
          updateMessage(messageId, (msg) => {
            const nextRunState = msg.runId
              ? createTerminalRunState(
                  msg.runId,
                  'failed',
                  msg.pipelineSteps,
                  getErrorMessage(e),
                  msg.runState
                )
              : msg.runState;
            return {
              ...msg,
              isStreaming: false,
              runState: nextRunState,
            };
          });
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
      applyStateEvent,
      applyUiEvent,
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

                <KbChatConfigPanel
                  value={kbChatConfig}
                  onChange={setKbChatConfig}
                  disabled={loading || loadingSession || knowledgeBasesQuery.isLoading}
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
        <Stack spacing={0.75}>
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2" color="text.secondary">
              已选择 {session.selected_kb_ids?.length || 0} 个知识库
            </Typography>
            {hasPendingClarification && (
              <Chip size="small" color="warning" label="等待补充信息" />
            )}
          </Stack>
          <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
            {enabledConfigLabels.slice(0, 6).map((label) => (
              <Chip key={label} size="small" label={label} variant="outlined" />
            ))}
            {enabledConfigLabels.length > 6 && (
              <Chip
                size="small"
                label={`+${enabledConfigLabels.length - 6}`}
                variant="outlined"
              />
            )}
          </Stack>
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
          bottomInset={bottomInset}
        />
      )}

      <ErrorAlert error={mergedError} onClose={handleCloseError} />

      <Box
        ref={composerRef}
        sx={{
          position: 'sticky',
          bottom: 0,
          p: { xs: 2, md: 3 },
          bgcolor: 'background.default',
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

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
  Drawer,
  Divider,
  Paper,
  Stack,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import InsightsIcon from '@mui/icons-material/Insights';
import { Button } from '../components/ui/Button';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { KbChatConfigPanel } from '../components/chat/KbChatConfigPanel';

import type { ChatMessage } from '../components/chat/MessageList';
import type {
  PipelineStep,
  PipelineTimelineEvent,
} from '../components/chat/PipelineProgress';

import {
  type AgentMode,
  type ChatRunStateEvent,
  type ChatRunUiEvent,
  type ChatNodeDisplayItem,
  type ChatNodeIoEvent,
  type KbGraphSchema,
  type KbChatConfig,
  type ChatMessageResponse,
  type ChatSession,
  createChatSession,
  getKbChatGraphSchema,
  isUnexpectedStreamEnd,
  resolveTerminalRunStatus,
  streamChatMessage,
  streamResumeClarification,
} from '../services/chats';
import { resolveKbNodeLabel } from '../services/kbNodeLabels';
import {
  kbChatTraceSelectors,
  reduceKbChatTraceState,
  type KbChatTraceStoreState,
} from '../services/kbChatTraceStore';
import { useSelectableKnowledgeBases } from '../hooks/queries/useKnowledgeBases';
import { useRecentHistory } from '../hooks/useRecentHistory';
import { WelcomeScreen } from '../components/chat/WelcomeScreen';
import { KbChatInputPanel } from '../components/chat/KbChatInputPanel';
import { ChatViewport } from '../components/chat/ChatViewport';
import { getErrorMessage } from '../lib/errorHandler';
import { useKbChatSessionController } from '../hooks/useKbChatSessionController';
import {
  applyMessagesEventToState,
  completeMessageState,
  createChatStreamMetricsCollector,
  createMessageState,
  createMessageStateBatcher,
  hasSelectedParentChildKnowledgeBase,
  parseSseJson,
  resolveActiveAssistantId,
  resolveFinalizeNodeIds,
  shouldRevealAnswerOnNodeEvent,
  validateKbChatConfig,
} from '../hooks/kbChatPageBoundary';
import { resolveAssistantContentByRunStatus } from './kb-chat/streamingRuntime';

const MessageList = dynamic(
  () => import('../components/chat/MessageList').then((mod) => mod.MessageList),
  { ssr: false }
);

const KnowledgeBaseSelector = dynamic(
  () => import('../components/KnowledgeBaseSelector').then((mod) => mod.KnowledgeBaseSelector),
  { ssr: false }
);

const KbChatFlowPanel = dynamic(
  () => import('../components/chat/KbChatFlowPanel').then((mod) => mod.KbChatFlowPanel),
  { ssr: false }
);

type TerminalRunStatus = 'succeeded' | 'failed' | 'canceled' | 'waiting_user';

const DEFAULT_KB_CHAT_CONFIG: KbChatConfig = {
  entity_expand_max_candidates: 8,
  entity_expand_max_variants: 6,
  entity_expand_min_confidence: 0.55,
  retrieval_top_k: 12,
  retrieval_rerank_top_k: 50,
  retrieval_hybrid_ranker: 'rrf',
  retrieval_hybrid_dense_weight: 0.6,
  retrieval_hybrid_sparse_weight: 0.4,
  retrieval_hybrid_rrf_k: 60,
  retrieval_parent_max_parents: 8,
  retrieval_parent_max_children_per_parent: 3,
  retrieval_multiscale_per_window_top_k: 40,
  retrieval_multiscale_rrf_k: 60,
  retrieval_multiscale_max_documents: 12,
  retrieval_multiscale_max_chunks_per_document: 2,
};

function sortPipelineSteps(steps: PipelineStep[]): PipelineStep[] {
  return [...steps].sort((a, b) => {
    const tsCompare = (a.ts ?? '').localeCompare(b.ts ?? '');
    if (tsCompare !== 0) {
      return tsCompare;
    }
    return a.step_id.localeCompare(b.step_id);
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

function createInitialRunState(runId: string, totalNodes = 1): ChatRunStateEvent {
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
      total: Math.max(1, totalNodes),
      percent: 0,
    },
    ts: new Date().toISOString(),
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

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function resolveGraphTotalNodes(schema: KbGraphSchema | null | undefined): number {
  if (!schema || !Array.isArray(schema.nodes) || schema.nodes.length === 0) {
    return 1;
  }
  return Math.max(1, schema.nodes.length);
}

function resolveClarificationStep(
  schema: KbGraphSchema | null | undefined
): { step_id: string; label: string } {
  const nodes = Array.isArray(schema?.nodes) ? [...schema.nodes] : [];
  if (nodes.length === 0) {
    return { step_id: 'waiting_user', label: '待补充信息' };
  }
  nodes.sort((a, b) => {
    const aOrder = typeof a.order === 'number' ? a.order : Number.MAX_SAFE_INTEGER;
    const bOrder = typeof b.order === 'number' ? b.order : Number.MAX_SAFE_INTEGER;
    if (aOrder !== bOrder) {
      return aOrder - bOrder;
    }
    return a.id.localeCompare(b.id);
  });
  const target = nodes.find((node) => node.phase === 'finalize') ?? nodes[nodes.length - 1];
  const label = typeof target.label === 'string' && target.label.trim() ? target.label : target.id;
  return { step_id: target.id, label };
}

function resolveClarificationAnchorStep(
  runState: ChatRunStateEvent | undefined,
  fallback: { step_id: string; label: string }
): { step_id: string; label: string } {
  const stepId =
    typeof runState?.current_step_id === 'string' && runState.current_step_id.trim()
      ? runState.current_step_id
      : typeof runState?.current_node === 'string' && runState.current_node.trim()
        ? runState.current_node
        : fallback.step_id;
  const label =
    typeof runState?.current_step_label === 'string' && runState.current_step_label.trim()
      ? runState.current_step_label
      : fallback.label;
  return { step_id: stepId, label };
}

function mergeActivePath(
  current: string[] | undefined,
  nodeIds: string[]
): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const nodeId of current ?? []) {
    if (!seen.has(nodeId)) {
      seen.add(nodeId);
      result.push(nodeId);
    }
  }
  for (const nodeId of nodeIds) {
    if (!seen.has(nodeId)) {
      seen.add(nodeId);
      result.push(nodeId);
    }
  }
  return result;
}

function buildProgressFromActivePath(
  activePath: string[] | undefined,
  totalNodes: number,
  runStatus: ChatRunStateEvent['run_status']
) {
  const completed = runStatus === 'succeeded'
    ? Math.max(1, totalNodes)
    : Math.min(Math.max(0, activePath?.length ?? 0), Math.max(1, totalNodes));
  const total = Math.max(1, totalNodes);
  const percent = total > 0 ? Math.min(100, Math.round((completed / total) * 1000) / 10) : 0;
  return { completed, total, percent };
}

function parseUpdatesChunk(data: Record<string, unknown>): Record<string, unknown> | null {
  const nested = asRecord(data.chunk);
  if (nested) {
    return nested;
  }
  return asRecord(data);
}

function parseNodeDisplayItems(value: unknown): ChatNodeDisplayItem[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const normalized: ChatNodeDisplayItem[] = [];
  for (const item of value) {
    const record = asRecord(item);
    if (!record) {
      continue;
    }
    const key = typeof record.key === 'string' ? record.key : null;
    const label = typeof record.label === 'string' ? record.label : null;
    const rawValue = record.value;
    if (!key || !label) {
      continue;
    }
    if (typeof rawValue === 'string') {
      normalized.push({ key, label, value: rawValue });
      continue;
    }
    if (Array.isArray(rawValue)) {
      const lines = rawValue.filter((line): line is string => typeof line === 'string');
      if (lines.length > 0) {
        normalized.push({ key, label, value: lines });
      }
    }
  }
  return normalized.length > 0 ? normalized : null;
}

function parseNodeIoEvent(data: Record<string, unknown>): ChatNodeIoEvent | null {
  const run = asRecord(data.run);
  const node = asRecord(data.node);
  const runId =
    typeof data.run_id === 'string'
      ? data.run_id
      : typeof run?.id === 'string'
        ? run.id
        : null;
  const nodeName =
    typeof data.node_name === 'string'
      ? data.node_name
      : typeof data.node === 'string'
        ? data.node
        : typeof node?.name === 'string'
          ? node.name
          : null;
  const nodeId =
    typeof data.node_id === 'string'
      ? data.node_id
      : typeof node?.id === 'string'
        ? node.id
        : nodeName;
  const phaseRaw = typeof data.phase === 'string' ? data.phase : null;
  const phase =
    phaseRaw === 'start' || phaseRaw === 'end' || phaseRaw === 'error'
      ? phaseRaw
      : null;
  if (!runId || !nodeName || !nodeId || !phase) {
    return null;
  }
  return {
    run_id: runId,
    node_name: nodeName,
    node_id: nodeId,
    phase,
    display_input_items: parseNodeDisplayItems(data.display_input_items),
    display_output_items: parseNodeDisplayItems(data.display_output_items),
    attempt: typeof data.attempt === 'number' ? data.attempt : null,
    latency_ms: typeof data.latency_ms === 'number' ? data.latency_ms : null,
    input_summary: asRecord(data.input_summary),
    output_summary: asRecord(data.output_summary),
    input_snapshot: asRecord(data.input_snapshot),
    output_snapshot: asRecord(data.output_snapshot),
    error_summary: typeof data.error_summary === 'string' ? data.error_summary : null,
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
    current_step_id:
      current?.step_id ?? (status === 'waiting_user' ? previousState?.current_step_id ?? null : null),
    current_step_label:
      current?.label ?? (status === 'waiting_user' ? previousState?.current_step_label ?? null : null),
    current_step_status: current?.status ?? (status === 'waiting_user' ? 'waiting_user' : null),
    current_node: current?.node ?? (status === 'waiting_user' ? previousState?.current_node ?? null : null),
    attempt:
      typeof current?.meta?.attempt === 'number'
        ? current.meta.attempt
        : status === 'waiting_user'
          ? previousState?.attempt ?? null
          : null,
    message: message ?? current?.message ?? null,
    state_version: previousState?.state_version,
    active_path: previousState?.active_path,
    last_good_answer: previousState?.last_good_answer,
    degrade_reason: previousState?.degrade_reason,
    progress: calculateProgress(sorted),
    ts: new Date().toISOString(),
  };
}

function isPendingClarificationResponse(
  response: ChatMessageResponse
): response is Extract<ChatMessageResponse, { status: 'pending_user_clarification' }> {
  return response.status === 'pending_user_clarification';
}

export function KbChatPage() {
  const theme = useTheme();
  const isTabletOrDown = useMediaQuery(theme.breakpoints.down('lg'));
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
  const clearSessionIdFromUrl = useCallback(() => {
    if (typeof window === 'undefined') {
      return;
    }
    const nextParams = new URLSearchParams(window.location.search);
    nextParams.delete('sessionId');
    replaceSearchParams(nextParams);
  }, [replaceSearchParams]);
  const knowledgeBasesQuery = useSelectableKnowledgeBases();
  const knowledgeBases = knowledgeBasesQuery.data;

  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [kbChatConfig, setKbChatConfig] = useState<KbChatConfig>(DEFAULT_KB_CHAT_CONFIG);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [graphSchema, setGraphSchema] = useState<KbGraphSchema | null>(null);
  const clarificationStep = useMemo(() => resolveClarificationStep(graphSchema), [graphSchema]);
  const finalizeNodeIds = useMemo(() => resolveFinalizeNodeIds(graphSchema), [graphSchema]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mobileTraceOpen, setMobileTraceOpen] = useState(false);

  useKbChatSessionController({
    sessionId,
    pathname,
    clearSessionIdFromUrl,
    setLoadingSession,
    setError,
    setSession,
    setMessages,
    setSelectedKbIds,
    setKbChatConfig,
    defaultConfig: DEFAULT_KB_CHAT_CONFIG,
  });

  const { upsertSession } = useRecentHistory();

  const mergedError = error ?? (knowledgeBasesQuery.error ? getErrorMessage(knowledgeBasesQuery.error) : null);

  const selectedKbNames = useMemo(() => {
    const map = new Map((knowledgeBases ?? []).map((kb) => [kb.id, kb.name]));
    return selectedKbIds.map((id) => map.get(id) ?? id);
  }, [knowledgeBases, selectedKbIds]);

  const activeConfig = session?.kb_chat_config ?? kbChatConfig;
  const initialConfigErrors = useMemo(() => validateKbChatConfig(kbChatConfig), [kbChatConfig]);
  const parentChildLimitsEnabled = useMemo(
    () => hasSelectedParentChildKnowledgeBase(selectedKbIds, knowledgeBases),
    [knowledgeBases, selectedKbIds]
  );

  const hasPendingClarification = useMemo(
    () => messages.some((msg) => Boolean(msg.pendingClarification)),
    [messages]
  );
  const [activeAssistantId, setActiveAssistantId] = useState<string | null>(null);

  const assistantMessages = useMemo(
    () => messages.filter((msg) => msg.role === 'assistant'),
    [messages]
  );

  useEffect(() => {
    const nextActiveAssistantId = resolveActiveAssistantId(
      assistantMessages,
      activeAssistantId
    );
    if (nextActiveAssistantId !== activeAssistantId) {
      setActiveAssistantId(nextActiveAssistantId);
    }
  }, [assistantMessages, activeAssistantId]);

  const activeAssistantMessage = useMemo(
    () =>
      assistantMessages.find((msg) => msg.id === activeAssistantId) ??
      assistantMessages[assistantMessages.length - 1] ??
      null,
    [assistantMessages, activeAssistantId]
  );

  useEffect(() => {
    if (!session) {
      setGraphSchema(null);
      return;
    }
    let active = true;
    const loadGraphSchema = async () => {
      try {
        const schema = await getKbChatGraphSchema(activeConfig);
        if (active) {
          setGraphSchema(schema);
        }
      } catch (e) {
        if (active) {
          setError(getErrorMessage(e));
        }
      }
    };
    void loadGraphSchema();
    return () => {
      active = false;
    };
  }, [activeConfig, session]);

  useEffect(() => {
    if (!isTabletOrDown) {
      setMobileTraceOpen(false);
    }
  }, [isTabletOrDown]);

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

  const applyUpdatesEvent = useCallback(
    (messageId: string, raw: Record<string, unknown>) => {
      const totalNodes = resolveGraphTotalNodes(graphSchema);
      updateMessage(messageId, (msg) => {
        const traceState: KbChatTraceStoreState = {
          runId: msg.runId,
          runState: msg.runState,
          pipelineSteps: msg.pipelineSteps,
          nodeTimeline: msg.nodeTimeline,
          nodeIoEvents: msg.nodeIoEvents,
          answerRevealReady: msg.answerRevealReady,
          traceWarnings: msg.traceWarnings,
        };
        const nextTraceState = reduceKbChatTraceState(
          traceState,
          { type: 'updates', raw },
          {
            totalNodes,
            resolveNodeLabel: (nodeId) => resolveKbNodeLabel(nodeId, graphSchema),
            shouldRevealAnswerOnNodeEvent: (event) =>
              shouldRevealAnswerOnNodeEvent(event, finalizeNodeIds),
          }
        );
        const answerRevealReady = Boolean(
          nextTraceState.answerRevealReady ?? msg.answerRevealReady
        );
        return {
          ...msg,
          runId: nextTraceState.runId ?? msg.runId,
          runState: kbChatTraceSelectors.runState(nextTraceState),
          pipelineSteps: kbChatTraceSelectors.pipelineSteps(nextTraceState),
          nodeTimeline: kbChatTraceSelectors.nodeTimeline(nextTraceState),
          nodeIoEvents: kbChatTraceSelectors.nodeIoEvents(nextTraceState),
          traceWarnings: kbChatTraceSelectors.warnings(nextTraceState),
          answerRevealReady,
          content: answerRevealReady ? msg.stagedContent ?? msg.content : msg.content,
        };
      });
    },
    [finalizeNodeIds, graphSchema, updateMessage]
  );

  const applyStateEvent = useCallback(
    (messageId: string, raw: Record<string, unknown>) => {
      const totalNodes = resolveGraphTotalNodes(graphSchema);
      updateMessage(messageId, (msg) => {
        const traceState: KbChatTraceStoreState = {
          runId: msg.runId,
          runState: msg.runState,
          pipelineSteps: msg.pipelineSteps,
          nodeTimeline: msg.nodeTimeline,
          nodeIoEvents: msg.nodeIoEvents,
          answerRevealReady: msg.answerRevealReady,
          traceWarnings: msg.traceWarnings,
        };
        const nextTraceState = reduceKbChatTraceState(
          traceState,
          { type: 'state', raw },
          {
            totalNodes,
            resolveNodeLabel: (nodeId) => resolveKbNodeLabel(nodeId, graphSchema),
            shouldRevealAnswerOnNodeEvent: (event) =>
              shouldRevealAnswerOnNodeEvent(event, finalizeNodeIds),
          }
        );
        return {
          ...msg,
          runId: nextTraceState.runId ?? msg.runId,
          runState: kbChatTraceSelectors.runState(nextTraceState),
          pipelineSteps: kbChatTraceSelectors.pipelineSteps(nextTraceState),
          nodeTimeline: kbChatTraceSelectors.nodeTimeline(nextTraceState),
          nodeIoEvents: kbChatTraceSelectors.nodeIoEvents(nextTraceState),
          traceWarnings: kbChatTraceSelectors.warnings(nextTraceState),
          answerRevealReady: nextTraceState.answerRevealReady ?? msg.answerRevealReady,
        };
      });
    },
    [finalizeNodeIds, graphSchema, updateMessage]
  );

const applyUiEvent = useCallback(
    (messageId: string, raw: Record<string, unknown>) => {
      const totalNodes = resolveGraphTotalNodes(graphSchema);
      updateMessage(messageId, (msg) => {
        const traceState: KbChatTraceStoreState = {
          runId: msg.runId,
          runState: msg.runState,
          pipelineSteps: msg.pipelineSteps,
          nodeTimeline: msg.nodeTimeline,
          nodeIoEvents: msg.nodeIoEvents,
          answerRevealReady: msg.answerRevealReady,
          traceWarnings: msg.traceWarnings,
        };
        const nextTraceState = reduceKbChatTraceState(
          traceState,
          { type: 'ui_event', raw },
          {
            totalNodes,
            resolveNodeLabel: (nodeId) => resolveKbNodeLabel(nodeId, graphSchema),
            shouldRevealAnswerOnNodeEvent: (event) =>
              shouldRevealAnswerOnNodeEvent(event, finalizeNodeIds),
          }
        );
        const nextRunState = kbChatTraceSelectors.runState(nextTraceState);
        const shouldUseCandidateFallback = Boolean(
          nextRunState &&
            typeof nextRunState.last_good_answer === 'string' &&
            nextRunState.last_good_answer.trim().length > 0 &&
            typeof raw.event_type === 'string' &&
            raw.event_type === 'degraded_to_candidate'
        );
        return {
          ...msg,
          runId: nextTraceState.runId ?? msg.runId,
          runState: nextRunState,
          pipelineSteps: kbChatTraceSelectors.pipelineSteps(nextTraceState),
          nodeTimeline: kbChatTraceSelectors.nodeTimeline(nextTraceState),
          nodeIoEvents: kbChatTraceSelectors.nodeIoEvents(nextTraceState),
          traceWarnings: kbChatTraceSelectors.warnings(nextTraceState),
          answerRevealReady: nextTraceState.answerRevealReady ?? msg.answerRevealReady,
          content: shouldUseCandidateFallback
            ? nextRunState?.last_good_answer ?? msg.content
            : msg.content,
        };
      });
    },
    [finalizeNodeIds, graphSchema, updateMessage]
  );

  const applyNodeIoEvent = useCallback(
    (messageId: string, raw: Record<string, unknown>) => {
      const totalNodes = resolveGraphTotalNodes(graphSchema);
      updateMessage(messageId, (msg) => {
        const traceState: KbChatTraceStoreState = {
          runId: msg.runId,
          runState: msg.runState,
          pipelineSteps: msg.pipelineSteps,
          nodeTimeline: msg.nodeTimeline,
          nodeIoEvents: msg.nodeIoEvents,
          answerRevealReady: msg.answerRevealReady,
          traceWarnings: msg.traceWarnings,
        };
        const nextTraceState = reduceKbChatTraceState(
          traceState,
          { type: 'node_io', raw },
          {
            totalNodes,
            resolveNodeLabel: (nodeId) => resolveKbNodeLabel(nodeId, graphSchema),
            shouldRevealAnswerOnNodeEvent: (event) =>
              shouldRevealAnswerOnNodeEvent(event, finalizeNodeIds),
          }
        );
        const answerRevealReady = Boolean(
          nextTraceState.answerRevealReady ?? msg.answerRevealReady
        );
        return {
          ...msg,
          runId: nextTraceState.runId ?? msg.runId,
          runState: kbChatTraceSelectors.runState(nextTraceState),
          answerRevealReady,
          content: answerRevealReady ? msg.stagedContent ?? msg.content : msg.content,
          pipelineSteps: kbChatTraceSelectors.pipelineSteps(nextTraceState),
          nodeIoEvents: kbChatTraceSelectors.nodeIoEvents(nextTraceState),
          nodeTimeline: kbChatTraceSelectors.nodeTimeline(nextTraceState),
          traceWarnings: kbChatTraceSelectors.warnings(nextTraceState),
        };
      });
    },
    [finalizeNodeIds, graphSchema, updateMessage]
  );

  const applyCustomEvent = useCallback(
    (messageId: string, raw: Record<string, unknown>) => {
      const totalNodes = resolveGraphTotalNodes(graphSchema);
      updateMessage(messageId, (msg) => {
        const traceState: KbChatTraceStoreState = {
          runId: msg.runId,
          runState: msg.runState,
          pipelineSteps: msg.pipelineSteps,
          nodeTimeline: msg.nodeTimeline,
          nodeIoEvents: msg.nodeIoEvents,
          answerRevealReady: msg.answerRevealReady,
          traceWarnings: msg.traceWarnings,
        };
        const nextTraceState = reduceKbChatTraceState(
          traceState,
          { type: 'custom', raw },
          {
            totalNodes,
            resolveNodeLabel: (nodeId) => resolveKbNodeLabel(nodeId, graphSchema),
            shouldRevealAnswerOnNodeEvent: (event) =>
              shouldRevealAnswerOnNodeEvent(event, finalizeNodeIds),
          }
        );
        return {
          ...msg,
          runId: nextTraceState.runId ?? msg.runId,
          runState: kbChatTraceSelectors.runState(nextTraceState),
          pipelineSteps: kbChatTraceSelectors.pipelineSteps(nextTraceState),
          nodeTimeline: kbChatTraceSelectors.nodeTimeline(nextTraceState),
          nodeIoEvents: kbChatTraceSelectors.nodeIoEvents(nextTraceState),
          traceWarnings: kbChatTraceSelectors.warnings(nextTraceState),
          answerRevealReady: nextTraceState.answerRevealReady ?? msg.answerRevealReady,
        };
      });
    },
    [finalizeNodeIds, graphSchema, updateMessage]
  );

  const applyHeartbeatEvent = useCallback(
    (messageId: string, raw: Record<string, unknown>) => {
      updateMessage(messageId, (msg) => ({
        ...msg,
        runState:
          msg.runState && typeof raw.ts === 'string'
            ? {
                ...msg.runState,
                ts: raw.ts,
              }
            : msg.runState,
      }));
    },
    [updateMessage]
  );

  const markClarificationPending = useCallback(
    (
      messageId: string,
      response: Extract<
        ChatMessageResponse,
        { status: 'pending_user_clarification' }
      >
    ) => {
      const runId = response.run.id;
      const message = response.message;
      updateMessage(messageId, (msg) => {
        const anchorStep = resolveClarificationAnchorStep(msg.runState, clarificationStep);
        const nextSteps = upsertPipelineStep(msg.pipelineSteps, {
          step_id: anchorStep.step_id,
          label: anchorStep.label,
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
          stagedContent: '',
          answerRevealReady: false,
          think: '',
          runId,
          pendingClarification: {
            message,
            pendingClarification: response.pending_clarification ?? null,
          },
          evidence: response.evidence ?? msg.evidence,
          confidenceScore: response.confidence_score ?? null,
          confidenceLevel: response.confidence_level ?? null,
          responseSource: response.source ?? 'live',
          cacheMeta: response.cache ?? null,
          pipelineSteps: nextSteps,
          runState: nextRunState,
          traceWarnings: msg.traceWarnings ?? [],
          isStreaming: false,
        };
      });
    },
    [clarificationStep, updateMessage]
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
        stagedContent: '',
        answerRevealReady: false,
        think: '',
        toolSteps: [],
        pipelineSteps: [],
        nodeTimeline: [],
        nodeIoEvents: [],
        traceWarnings: [],
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

    let hadStreamEvent = false;
    let sawFinalEvent = false;
    let sawErrorEvent = false;
    const streamMetrics = createChatStreamMetricsCollector();
    const deltaBatcher = createMessageStateBatcher((nextState) => {
      updateMessage(assistantId, (msg) => {
        const content = msg.answerRevealReady ? nextState.final_content : msg.content;
        return {
          ...msg,
          content,
          stagedContent: nextState.final_content,
          think: nextState.thought_log,
          toolSteps: nextState.tool_steps,
          isStreaming: true,
        };
      });
    });

    try {
      const stream = await streamChatMessage(session.id, userContent);
      touchRecent();
      for await (const event of stream) {
        hadStreamEvent = true;
        streamMetrics.onEvent(event.event);
        if (event.event === 'meta') {
          const meta = parseSseJson<{ run_id?: string }>(event.data);
          const runIdFromMeta = meta.run_id;
          if (runIdFromMeta) {
            updateMessage(assistantId, (msg) => {
              const nextRunState =
                msg.runState ??
                createInitialRunState(
                  runIdFromMeta,
                  resolveGraphTotalNodes(graphSchema)
                );
              return {
                ...msg,
                runId: runIdFromMeta,
                runState: nextRunState,
              };
            });
          }
        }

        if (event.event === 'updates') {
          applyUpdatesEvent(assistantId, parseSseJson<Record<string, unknown>>(event.data));
        }

        if (event.event === 'state') {
          applyStateEvent(assistantId, parseSseJson<Record<string, unknown>>(event.data));
        }

        if (event.event === 'ui_event') {
          applyUiEvent(assistantId, parseSseJson<Record<string, unknown>>(event.data));
        }
        if (event.event === 'messages') {
          const data = parseSseJson<Record<string, unknown>>(event.data);
          msgState = applyMessagesEventToState(msgState, data);
          deltaBatcher.push(msgState);
        }
        if (event.event === 'node_io') {
          applyNodeIoEvent(assistantId, parseSseJson<Record<string, unknown>>(event.data));
        }
        if (event.event === 'custom') {
          applyCustomEvent(assistantId, parseSseJson<Record<string, unknown>>(event.data));
        }
        if (event.event === 'heartbeat') {
          applyHeartbeatEvent(assistantId, parseSseJson<Record<string, unknown>>(event.data));
        }
        if (event.event === 'stream_end') {
          const data = parseSseJson<Record<string, unknown>>(event.data);
          const terminalCandidate =
            typeof data.terminal_candidate === 'string' ? data.terminal_candidate : null;
          if (terminalCandidate) {
            updateMessage(assistantId, (msg) => ({
              ...msg,
              runState: msg.runState
                ? {
                    ...msg.runState,
                    message: `终态候选: ${terminalCandidate}`,
                    ts:
                      typeof data.ts === 'string'
                        ? data.ts
                        : msg.runState.ts ?? new Date().toISOString(),
                  }
                : msg.runState,
            }));
          }
        }

        if (event.event === 'interrupt') {
          deltaBatcher.flush();
          const data = parseSseJson<ChatMessageResponse>(event.data);
          if (isPendingClarificationResponse(data)) {
            markClarificationPending(assistantId, data);
            setLoading(false);
            return;
          }
        }

        if (event.event === 'final') {
          sawFinalEvent = true;
          deltaBatcher.flush();
          const data = parseSseJson<ChatMessageResponse>(event.data);
          if (data.status === 'succeeded') {
            updateMessage(assistantId, (msg) => {
              const nextSteps = finalizePipelineSteps(msg.pipelineSteps);
              const nextStatus = resolveTerminalRunStatus(
                data.run.status,
                resolveTerminalRunStatus(msg.runState?.run_status)
              );
              const nextRunState = createTerminalRunState(
                data.run.id,
                nextStatus,
                nextSteps,
                undefined,
                msg.runState
              );
              const finalContent = resolveAssistantContentByRunStatus({
                status: nextStatus,
                serverContent: data.assistant_message.content,
                lastGoodAnswer: nextRunState.last_good_answer,
              });
              return {
                ...msg,
                id: data.assistant_message.id,
                content: finalContent,
                stagedContent: finalContent,
                answerRevealReady: true,
                evidence: data.evidence,
                confidenceScore: data.confidence_score ?? null,
                confidenceLevel: data.confidence_level ?? null,
                responseSource: data.source ?? 'live',
                cacheMeta: data.cache ?? null,
                runId: data.run.id,
                pipelineSteps: nextSteps,
                runState: nextRunState,
                pendingClarification: undefined,
                isStreaming: false,
              };
            });
          }
          setLoading(false);
          console.info('kb-chat-stream-metrics', streamMetrics.finalize());
          return;
        }

        if (event.event === 'error') {
          sawErrorEvent = true;
          deltaBatcher.flush();
          const err = parseSseJson<{ message?: string }>(event.data);
          throw new Error(err?.message ?? '流式响应失败');
        }
      }

      if (isUnexpectedStreamEnd({ sawFinalEvent, sawErrorEvent })) {
        throw new Error('Stream ended unexpectedly without a terminal event');
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
          content: msg.answerRevealReady ? msgState.final_content : msg.content,
          stagedContent: msgState.final_content,
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
        streamMetrics.onFailure();
        console.info('kb-chat-stream-metrics', streamMetrics.finalize());
        return;
      }
      setError(getErrorMessage(e));
      streamMetrics.onFailure();
    } finally {
      deltaBatcher.flush();
      console.info('kb-chat-stream-metrics', streamMetrics.finalize());
      setLoading(false);
    }
  }, [
    session,
    graphSchema,
    input,
    loading,
    loadingSession,
    hasPendingClarification,
    upsertSession,
    updateMessage,
    applyUpdatesEvent,
    applyStateEvent,
    applyUiEvent,
    applyNodeIoEvent,
    applyCustomEvent,
    applyHeartbeatEvent,
    markClarificationPending,
  ]);

  const handleClarificationSubmit = useCallback(
    async (messageId: string, runId: string, content: string) => {
      if (!session || loading || loadingSession) return;

      setLoading(true);
      setError(null);
      let msgState = createMessageState();
      updateMessage(messageId, (msg) => {
        const anchorStep = resolveClarificationAnchorStep(msg.runState, clarificationStep);
        const nextSteps = upsertPipelineStep(msg.pipelineSteps, {
          step_id: anchorStep.step_id,
          label: anchorStep.label,
          status: 'started',
          message: '已收到补充信息，继续执行',
          ts: new Date().toISOString(),
        });
        const startedStep = nextSteps.find((step) => step.step_id === anchorStep.step_id);
        return {
          ...msg,
          content: '',
          stagedContent: '',
          answerRevealReady: false,
          think: '',
          pendingClarification: undefined,
          pipelineSteps: nextSteps,
          traceWarnings: [],
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

      let hadStreamEvent = false;
      let sawFinalEvent = false;
      let sawErrorEvent = false;
      const streamMetrics = createChatStreamMetricsCollector();
      const deltaBatcher = createMessageStateBatcher((nextState) => {
        updateMessage(messageId, (msg) => {
          const content = msg.answerRevealReady ? nextState.final_content : msg.content;
          return {
            ...msg,
            content,
            stagedContent: nextState.final_content,
            think: nextState.thought_log,
            toolSteps: nextState.tool_steps,
            isStreaming: true,
          };
        });
      });

      try {
        const stream = await streamResumeClarification(session.id, runId, content);
        for await (const event of stream) {
          hadStreamEvent = true;
          streamMetrics.onEvent(event.event);
          if (event.event === 'meta') {
            const meta = parseSseJson<{ run_id?: string }>(event.data);
            const runIdFromMeta = meta.run_id;
            if (runIdFromMeta) {
              updateMessage(messageId, (msg) => {
                const nextRunState =
                  msg.runState ??
                  createInitialRunState(
                    runIdFromMeta,
                    resolveGraphTotalNodes(graphSchema)
                  );
                return {
                  ...msg,
                  runId: runIdFromMeta,
                  runState: nextRunState,
                };
              });
            }
          }

          if (event.event === 'updates') {
            applyUpdatesEvent(messageId, parseSseJson<Record<string, unknown>>(event.data));
          }

          if (event.event === 'state') {
            applyStateEvent(messageId, parseSseJson<Record<string, unknown>>(event.data));
          }

          if (event.event === 'ui_event') {
            applyUiEvent(messageId, parseSseJson<Record<string, unknown>>(event.data));
          }
          if (event.event === 'messages') {
            const data = parseSseJson<Record<string, unknown>>(event.data);
            msgState = applyMessagesEventToState(msgState, data);
            deltaBatcher.push(msgState);
          }
          if (event.event === 'node_io') {
            applyNodeIoEvent(messageId, parseSseJson<Record<string, unknown>>(event.data));
          }
          if (event.event === 'custom') {
            applyCustomEvent(messageId, parseSseJson<Record<string, unknown>>(event.data));
          }
          if (event.event === 'heartbeat') {
            applyHeartbeatEvent(messageId, parseSseJson<Record<string, unknown>>(event.data));
          }
          if (event.event === 'stream_end') {
            const data = parseSseJson<Record<string, unknown>>(event.data);
            const terminalCandidate =
              typeof data.terminal_candidate === 'string' ? data.terminal_candidate : null;
            if (terminalCandidate) {
              updateMessage(messageId, (msg) => ({
                ...msg,
                runState: msg.runState
                  ? {
                      ...msg.runState,
                      message: `终态候选: ${terminalCandidate}`,
                      ts:
                        typeof data.ts === 'string'
                          ? data.ts
                          : msg.runState.ts ?? new Date().toISOString(),
                    }
                  : msg.runState,
              }));
            }
          }

          if (event.event === 'interrupt') {
            deltaBatcher.flush();
            const data = parseSseJson<ChatMessageResponse>(event.data);
            if (isPendingClarificationResponse(data)) {
              markClarificationPending(messageId, data);
              setLoading(false);
              console.info('kb-chat-stream-metrics', streamMetrics.finalize());
              return;
            }
          }

          if (event.event === 'final') {
            sawFinalEvent = true;
            deltaBatcher.flush();
            const data = parseSseJson<ChatMessageResponse>(event.data);
            if (data.status === 'succeeded') {
              updateMessage(messageId, (msg) => {
                const nextSteps = finalizePipelineSteps(msg.pipelineSteps);
                const nextStatus = resolveTerminalRunStatus(
                  data.run.status,
                  resolveTerminalRunStatus(msg.runState?.run_status)
                );
                const nextRunState = createTerminalRunState(
                  data.run.id,
                  nextStatus,
                  nextSteps,
                  undefined,
                  msg.runState
                );
                const finalContent = resolveAssistantContentByRunStatus({
                  status: nextStatus,
                  serverContent: data.assistant_message.content,
                  lastGoodAnswer: nextRunState.last_good_answer,
                });
                return {
                  ...msg,
                  id: data.assistant_message.id,
                  content: finalContent,
                  stagedContent: finalContent,
                  answerRevealReady: true,
                  evidence: data.evidence,
                  confidenceScore: data.confidence_score ?? null,
                  confidenceLevel: data.confidence_level ?? null,
                  responseSource: data.source ?? 'live',
                  cacheMeta: data.cache ?? null,
                  runId: data.run.id,
                  pendingClarification: undefined,
                  pipelineSteps: nextSteps,
                  runState: nextRunState,
                  isStreaming: false,
                };
              });
            }
            setLoading(false);
            console.info('kb-chat-stream-metrics', streamMetrics.finalize());
            return;
          }

          if (event.event === 'error') {
            sawErrorEvent = true;
            deltaBatcher.flush();
            const err = parseSseJson<{ message?: string }>(event.data);
            throw new Error(err?.message ?? '恢复执行失败');
          }
        }

        if (isUnexpectedStreamEnd({ sawFinalEvent, sawErrorEvent })) {
          throw new Error('Stream ended unexpectedly without a terminal event');
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
            content: msg.answerRevealReady ? msgState.final_content : msg.content,
            stagedContent: msgState.final_content,
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
          streamMetrics.onFailure();
          console.info('kb-chat-stream-metrics', streamMetrics.finalize());
          return;
        }
        setError(getErrorMessage(e));
        streamMetrics.onFailure();
      } finally {
        deltaBatcher.flush();
        console.info('kb-chat-stream-metrics', streamMetrics.finalize());
        setLoading(false);
      }
    },
    [
      session,
      graphSchema,
      clarificationStep,
      loading,
      loadingSession,
      updateMessage,
      applyUpdatesEvent,
      applyStateEvent,
      applyUiEvent,
      applyNodeIoEvent,
      applyCustomEvent,
      applyHeartbeatEvent,
      markClarificationPending,
    ]
  );

  const resetSession = useCallback(() => {
    setSession(null);
    setMessages([]);
    setGraphSchema(null);
    setError(null);
    setActiveAssistantId(null);
    setMobileTraceOpen(false);
  }, []);

  if (!session) {
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          height: { xs: '100%', lg: '100dvh' },
          maxHeight: '100%',
          minHeight: 0,
          position: 'relative',
          overflow: 'hidden',
          px: { xs: 1.5, md: 3 },
          py: { xs: 2, md: 3 },
        }}
      >
        <Box
          sx={{
            position: 'absolute',
            inset: -120,
            background: (theme) =>
              theme.palette.mode === 'light'
                ? `radial-gradient(560px 260px at 12% 8%, ${alpha(theme.palette.primary.main, 0.14)} 0%, transparent 65%),
                   radial-gradient(520px 240px at 88% 14%, ${alpha(theme.palette.success.main, 0.1)} 0%, transparent 62%)`
                : `radial-gradient(560px 260px at 12% 8%, ${alpha(theme.palette.primary.main, 0.12)} 0%, transparent 65%),
                   radial-gradient(520px 240px at 88% 14%, ${alpha(theme.palette.success.main, 0.08)} 0%, transparent 62%)`,
            pointerEvents: 'none',
            zIndex: 0,
          }}
        />

        <Box
          sx={{
            position: 'relative',
            zIndex: 1,
            flex: 1,
            minHeight: 0,
            width: '100%',
            display: 'flex',
            flexDirection: 'column',
            gap: { xs: 1.5, md: 2 },
            overflowX: 'hidden',
            overflowY: 'auto',
            overscrollBehaviorY: 'contain',
            pb: { xs: 0.5, md: 1 },
          }}
        >
          <Stack
            spacing={2.2}
            sx={{
              width: '100%',
              px: { xs: 0.5, md: 1 },
            }}
          >
            <Stack spacing={1.25}>
              <Stack direction='row' spacing={1} alignItems='center'>
                <Chip size='small' color='primary' variant='outlined' label='知识工作区' />
                <Typography variant='caption' color='text.secondary'>
                  已就绪
                </Typography>
              </Stack>
              <Stack direction='row' alignItems='center' spacing={1}>
                <AutoAwesomeIcon color='primary' fontSize='small' />
                <Typography
                  variant='h4'
                  fontWeight={700}
                  sx={{
                    fontSize: { xs: '1.55rem', md: '2rem' },
                    letterSpacing: '-0.01em',
                  }}
                >
                  面向知识库的可观测问答
                </Typography>
              </Stack>
            </Stack>

            <Divider />

            <Stack spacing={0.8}>
              <Typography variant='subtitle1' fontWeight={700}>
                选择知识库
              </Typography>
              <Typography variant='body2' color='text.secondary'>
                支持多库联合检索，建议优先选择 1-3 个最相关知识库。
              </Typography>
            </Stack>

            <KnowledgeBaseSelector
              knowledgeBases={knowledgeBases ?? []}
              selectedIds={selectedKbIds}
              onToggle={toggleKb}
              loading={loading || loadingSession || knowledgeBasesQuery.isLoading}
            />

            {selectedKbNames.length > 0 && (
              <Stack direction='row' spacing={0.75} flexWrap='wrap' useFlexGap>
                {selectedKbNames.slice(0, 5).map((name) => (
                  <Chip key={name} label={name} size='small' color='primary' variant='outlined' />
                ))}
                {selectedKbNames.length > 5 && (
                  <Chip label={`+${selectedKbNames.length - 5}`} size='small' variant='outlined' />
                )}
              </Stack>
            )}

            <Divider />

            <KbChatConfigPanel
              value={kbChatConfig}
              onChange={setKbChatConfig}
              disabled={loading || loadingSession || knowledgeBasesQuery.isLoading}
              parentChildLimitsEnabled={parentChildLimitsEnabled}
            />

            <Stack
              direction='row'
              justifyContent='flex-end'
            >
              <Button
                variant='contained'
                onClick={startSession}
                disabled={
                  loadingSession ||
                  knowledgeBasesQuery.isLoading ||
                  selectedKbIds.length === 0 ||
                  initialConfigErrors.length > 0
                }
                loading={loading || loadingSession}
              >
                开始对话
              </Button>
            </Stack>
          </Stack>
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
        height: { xs: '100%', lg: '100dvh' },
        maxHeight: '100%',
        minHeight: 0,
        overflow: 'hidden',
        position: 'relative',
        px: { xs: 1, md: 2.5 },
        py: { xs: 1, md: 1.5 },
      }}
    >
      <Box
        sx={{
          position: 'absolute',
          inset: -90,
          background: (theme) =>
            theme.palette.mode === 'light'
              ? `radial-gradient(860px 360px at 8% 2%, ${alpha(theme.palette.primary.main, 0.2)} 0%, transparent 64%),
                 radial-gradient(720px 280px at 94% 8%, ${alpha(theme.palette.success.main, 0.15)} 0%, transparent 64%)`
              : `radial-gradient(860px 360px at 8% 2%, ${alpha(theme.palette.primary.main, 0.16)} 0%, transparent 64%),
                 radial-gradient(720px 280px at 94% 8%, ${alpha(theme.palette.success.main, 0.1)} 0%, transparent 64%)`,
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />

      <Paper
        variant='outlined'
        sx={{
          position: 'relative',
          zIndex: 1,
          p: { xs: 1.25, md: 1.5 },
          borderRadius: 3,
          mb: 1,
          borderColor: (theme) => alpha(theme.palette.primary.main, 0.2),
          bgcolor: (theme) =>
            theme.palette.mode === 'light'
              ? alpha(theme.palette.background.paper, 0.85)
              : alpha(theme.palette.background.paper, 0.52),
          backdropFilter: 'blur(14px)',
          WebkitBackdropFilter: 'blur(14px)',
        }}
      >
        <Stack spacing={1.1}>
          <Stack direction='row' alignItems='center' justifyContent='space-between' spacing={1}>
            <Stack direction='row' spacing={1} alignItems='center'>
              <Chip size='small' color='primary' variant='outlined' label='知识库问答会话' />
              <Typography variant='caption' color='text.secondary'>
                {new Date().toLocaleTimeString('zh-CN', { hour12: false })}
              </Typography>
            </Stack>
            <Stack direction='row' spacing={1}>
              {isTabletOrDown && (
                <Button
                  variant='outlined'
                  size='small'
                  startIcon={<InsightsIcon />}
                  onClick={() => setMobileTraceOpen(true)}
                >
                  推理过程
                </Button>
              )}
              <Button
                variant='outlined'
                size='small'
                startIcon={<RestartAltIcon />}
                onClick={resetSession}
              >
                重新选择
              </Button>
            </Stack>
          </Stack>

          <Stack direction='row' spacing={0.75} useFlexGap flexWrap='wrap'>
            <Chip size='small' label={`知识库 ${session.selected_kb_ids?.length || 0} 个`} />
            {selectedKbNames.slice(0, 4).map((name) => (
              <Chip key={`selected-kb-${name}`} size='small' variant='outlined' label={name} />
            ))}
            {selectedKbNames.length > 4 && (
              <Chip size='small' variant='outlined' label={`+${selectedKbNames.length - 4}`} />
            )}
            {hasPendingClarification && <Chip size='small' color='warning' label='等待补充信息' />}
          </Stack>
        </Stack>
      </Paper>

      <Box
        sx={{
          position: 'relative',
          zIndex: 1,
          flex: 1,
          minHeight: 0,
          overflow: 'hidden',
        }}
      >
        <Box
          sx={{
            display: 'grid',
            gap: 1,
            gridTemplateColumns: {
              xs: '1fr',
              lg: 'minmax(0, 1fr) minmax(320px, 400px)',
            },
            height: '100%',
            minHeight: 0,
            overflow: 'hidden',
          }}
        >
          <Paper
            variant='outlined'
            sx={{
              height: '100%',
              p: { xs: 0.75, md: 1 },
              borderRadius: 3,
              borderColor: (theme) => alpha(theme.palette.primary.main, 0.18),
              bgcolor: (theme) =>
                theme.palette.mode === 'light'
                  ? alpha(theme.palette.background.paper, 0.86)
                  : alpha(theme.palette.background.paper, 0.46),
              backdropFilter: 'blur(12px)',
              WebkitBackdropFilter: 'blur(12px)',
              display: 'flex',
              flexDirection: 'column',
              minHeight: 0,
              overflow: 'hidden',
            }}
          >
            <Box
              sx={{
                px: { xs: 1, md: 1.5 },
                pt: 1,
                pb: 0.5,
              }}
            >
              <Typography variant='subtitle1' fontWeight={700}>
                知识库问答
              </Typography>
              <Typography variant='caption' color='text.secondary'>
                选中一条助手回复，可在右侧查看对应运行链路
              </Typography>
            </Box>

            <ChatViewport
              lockPageScrollOnDesktop
              messagesSx={{ mt: 0.5 }}
              renderMessages={({ bottomInset }) =>
                messages.length === 0 ? (
                  <Stack
                    spacing={1.5}
                    sx={{
                      height: '100%',
                      px: { xs: 2, md: 2.5 },
                      py: { xs: 2, md: 3 },
                      justifyContent: 'center',
                    }}
                  >
                    <WelcomeScreen title='开始提问吧' suggestions={[]} />
                  </Stack>
                ) : (
                  <MessageList
                    messages={messages}
                    loading={loading || loadingSession}
                    onClarificationSubmit={handleClarificationSubmit}
                    approvalLoading={loading || loadingSession}
                    bottomInset={bottomInset}
                    showPipeline={false}
                    showEvidence
                    normalizeInlineEvidenceSection
                    scrollButtonAlign='right'
                    showScrollToBottom={false}
                    selectedAssistantId={activeAssistantMessage?.id ?? null}
                    onAssistantSelect={setActiveAssistantId}
                  />
                )
              }
              renderComposer={({ composerRef }) => (
                <KbChatInputPanel
                  composerRef={composerRef}
                  value={input}
                  onChange={setInput}
                  onSend={handleSend}
                  disabled={loading || loadingSession || hasPendingClarification}
                  loading={loading || loadingSession}
                  hasPendingClarification={hasPendingClarification}
                />
              )}
            />
          </Paper>

          {!isTabletOrDown && (
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'column',
                height: '100%',
                minHeight: 0,
                overflow: 'hidden',
              }}
            >
              <KbChatFlowPanel
                schema={graphSchema}
                runState={activeAssistantMessage?.runState}
                pipelineSteps={activeAssistantMessage?.pipelineSteps}
                nodeIoEvents={activeAssistantMessage?.nodeIoEvents}
                traceWarnings={activeAssistantMessage?.traceWarnings}
              />
            </Box>
          )}
        </Box>
      </Box>

      <Drawer
        anchor='right'
        open={isTabletOrDown && mobileTraceOpen}
        onClose={() => setMobileTraceOpen(false)}
        ModalProps={{ keepMounted: true }}
        PaperProps={{
          sx: {
            width: { xs: '100%', sm: 440 },
            p: 1.2,
            display: 'flex',
            flexDirection: 'column',
            minHeight: 0,
            bgcolor: (theme) =>
              theme.palette.mode === 'light'
                ? alpha(theme.palette.background.default, 0.96)
                : alpha(theme.palette.background.default, 0.96),
          },
        }}
      >
        <KbChatFlowPanel
          schema={graphSchema}
          runState={activeAssistantMessage?.runState}
          pipelineSteps={activeAssistantMessage?.pipelineSteps}
          nodeIoEvents={activeAssistantMessage?.nodeIoEvents}
          traceWarnings={activeAssistantMessage?.traceWarnings}
        />
      </Drawer>

      <ErrorAlert error={mergedError} onClose={handleCloseError} />
    </Box>
  );
}

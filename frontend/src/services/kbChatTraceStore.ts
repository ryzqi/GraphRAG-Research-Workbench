import type {
  ChatNodeDisplayItem,
  ChatNodeIoEvent,
  ChatRunStateEvent,
  ChatRunUiEvent,
  ChatTraceExecution,
  ChatTraceExecutionStatus,
} from './chats';
import { KB_CHAT_CUSTOM_EVENT_TYPES } from './chats';

export interface KbChatTraceStoreState {
  runId?: string;
  runState?: ChatRunStateEvent;
  executionsById?: Record<string, ChatTraceExecution>;
  executionOrder?: string[];
  answerRevealReady?: boolean;
  traceWarnings?: string[];
}

export type KbChatTraceAction =
  | { type: 'meta'; runId: string }
  | { type: 'state'; raw: Record<string, unknown> }
  | { type: 'updates'; raw: Record<string, unknown>; ts?: string }
  | { type: 'ui_event'; raw: Record<string, unknown> }
  | { type: 'custom'; raw: Record<string, unknown> }
  | { type: 'step'; raw: Record<string, unknown> }
  | { type: 'node_io'; raw: Record<string, unknown> };

export interface KbChatTraceReducerContext {
  totalNodes: number;
  resolveNodeLabel: (nodeId: string) => string;
  shouldRevealAnswerOnNodeEvent?: (event: ChatNodeIoEvent) => boolean;
}

interface ParsedStepEvent {
  executionId: string;
  runId: string;
  nodeName: string;
  status: ChatTraceExecutionStatus;
  ts: string;
  attempt?: number | null;
  nodePath?: string[] | null;
}

interface ParsedCustomEvent {
  runId: string;
  eventType: string;
  ts: string;
  message: string | null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function parseStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const normalized = value.filter(
    (item): item is string => typeof item === 'string' && item.trim().length > 0
  );
  return normalized.length > 0 ? normalized : null;
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

function mergeActivePath(current: string[] | undefined, nodeIds: string[]): string[] {
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
  const completed =
    runStatus === 'succeeded'
      ? Math.max(1, totalNodes)
      : Math.min(Math.max(0, activePath?.length ?? 0), Math.max(1, totalNodes));
  const total = Math.max(1, totalNodes);
  const percent = total > 0 ? Math.min(100, Math.round((completed / total) * 1000) / 10) : 0;
  return { completed, total, percent };
}

function createInitialRunState(runId: string, totalNodes: number): ChatRunStateEvent {
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

function appendTraceWarning(warnings: string[] | undefined, warning: string): string[] {
  return [...(warnings ?? []), warning].slice(-20);
}

function normalizeExecutionStatus(status: string | null | undefined): ChatTraceExecutionStatus | null {
  switch (status) {
    case 'running':
    case 'started':
      return 'started';
    case 'succeeded':
    case 'completed':
      return 'completed';
    case 'failed':
      return 'failed';
    case 'waiting_user':
      return 'waiting_user';
    case 'skipped':
      return 'skipped';
    default:
      return null;
  }
}

function isTerminalExecutionStatus(status: ChatTraceExecutionStatus): boolean {
  return (
    status === 'completed' ||
    status === 'failed' ||
    status === 'waiting_user' ||
    status === 'skipped'
  );
}

function hasAuthoritativeRunState(runState: ChatRunStateEvent | undefined): boolean {
  return Boolean(runState && typeof runState.state_version === 'number');
}

function normalizeNodeEventStatus(phase: ChatNodeIoEvent['phase']): ChatTraceExecutionStatus {
  switch (phase) {
    case 'start':
      return 'started';
    case 'error':
      return 'failed';
    default:
      return 'completed';
  }
}

function parseStepEvent(data: Record<string, unknown>): ParsedStepEvent | null {
  const runEnvelope = asRecord(data.run);
  const runId =
    typeof data.run_id === 'string'
      ? data.run_id
      : typeof runEnvelope?.id === 'string'
        ? runEnvelope.id
        : null;
  const executionId = typeof data.execution_id === 'string' ? data.execution_id : null;
  const stepId = typeof data.step_id === 'string' ? data.step_id : null;
  const status = normalizeExecutionStatus(typeof data.status === 'string' ? data.status : null);
  if (!runId || !executionId || !stepId || !status) {
    return null;
  }
  const meta = asRecord(data.meta);
  return {
    executionId,
    runId,
    nodeName:
      typeof data.node === 'string' && data.node.trim().length > 0 ? data.node : stepId,
    status,
    ts: typeof data.ts === 'string' ? data.ts : new Date().toISOString(),
    attempt: typeof meta?.attempt === 'number' ? meta.attempt : null,
    nodePath: parseStringArray(meta?.node_path),
  };
}

function parseState(data: Record<string, unknown>): ChatRunStateEvent | null {
  const runId = typeof data.run_id === 'string' ? data.run_id : null;
  const runStatus = typeof data.run_status === 'string' ? data.run_status : null;
  if (!runId || !runStatus) {
    return null;
  }
  const progressRaw = asRecord(data.progress) ?? {};
  const next: ChatRunStateEvent = {
    run_id: runId,
    run_status: runStatus as ChatRunStateEvent['run_status'],
    current_step_id: typeof data.current_step_id === 'string' ? data.current_step_id : null,
    current_step_label:
      typeof data.current_step_label === 'string' ? data.current_step_label : null,
    current_step_status:
      typeof data.current_step_status === 'string' ? data.current_step_status : null,
    current_node: typeof data.current_node === 'string' ? data.current_node : null,
    attempt: typeof data.attempt === 'number' ? data.attempt : null,
    message: typeof data.message === 'string' ? data.message : null,
    progress: {
      completed: typeof progressRaw.completed === 'number' ? progressRaw.completed : 0,
      total: typeof progressRaw.total === 'number' ? progressRaw.total : 1,
      percent: typeof progressRaw.percent === 'number' ? progressRaw.percent : 0,
    },
    ts: typeof data.ts === 'string' ? data.ts : new Date().toISOString(),
  };
  if (typeof data.state_version === 'number') {
    next.state_version = data.state_version;
  }
  if (Array.isArray(data.active_path)) {
    next.active_path = data.active_path.filter((item): item is string => typeof item === 'string');
  }
  if (typeof data.last_good_answer === 'string' || data.last_good_answer === null) {
    next.last_good_answer = data.last_good_answer;
  }
  if (typeof data.degrade_reason === 'string' || data.degrade_reason === null) {
    next.degrade_reason = data.degrade_reason;
  }
  return next;
}

function parseUiEvent(data: Record<string, unknown>): ChatRunUiEvent | null {
  const runId = typeof data.run_id === 'string' ? data.run_id : '';
  const eventType = typeof data.event_type === 'string' ? data.event_type : '';
  if (!runId || !eventType) return null;
  return {
    event_type: eventType,
    run_id: runId,
    step_id: typeof data.step_id === 'string' ? data.step_id : null,
    status: typeof data.status === 'string' ? data.status : null,
    node: typeof data.node === 'string' ? data.node : null,
    message: typeof data.message === 'string' ? data.message : null,
    candidate_answer:
      typeof data.candidate_answer === 'string' ? data.candidate_answer : null,
    source_step_id: typeof data.source_step_id === 'string' ? data.source_step_id : null,
    degrade_reason: typeof data.degrade_reason === 'string' ? data.degrade_reason : null,
    meta:
      data.meta && typeof data.meta === 'object'
        ? (data.meta as Record<string, unknown>)
        : null,
    ts: typeof data.ts === 'string' ? data.ts : new Date().toISOString(),
  };
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
  const phase = phaseRaw === 'start' || phaseRaw === 'end' || phaseRaw === 'error' ? phaseRaw : null;
  if (!runId || !nodeName || !nodeId || !phase) {
    return null;
  }
  return {
    execution_id: typeof data.execution_id === 'string' ? data.execution_id : null,
    run_id: runId,
    node_name: nodeName,
    node_id: nodeId,
    node_path: parseStringArray(data.node_path),
    phase,
    display_input_items: parseNodeDisplayItems(data.display_input_items),
    display_output_items: parseNodeDisplayItems(data.display_output_items),
    attempt: typeof data.attempt === 'number' ? data.attempt : null,
    latency_ms: typeof data.latency_ms === 'number' ? data.latency_ms : null,
    input_summary: asRecord(data.input_summary),
    output_summary: asRecord(data.output_summary),
    input_snapshot_meta: asRecord(data.input_snapshot_meta),
    output_snapshot_meta: asRecord(data.output_snapshot_meta),
    input_snapshot: asRecord(data.input_snapshot),
    output_snapshot: asRecord(data.output_snapshot),
    error_summary: typeof data.error_summary === 'string' ? data.error_summary : null,
    ts: typeof data.ts === 'string' ? data.ts : new Date().toISOString(),
  };
}

function parseCustomEvent(data: Record<string, unknown>): ParsedCustomEvent | null {
  const run = asRecord(data.run);
  const runId =
    typeof data.run_id === 'string'
      ? data.run_id
      : typeof run?.id === 'string'
        ? run.id
        : null;
  const eventType = typeof data.event_type === 'string' ? data.event_type : null;
  if (!runId || !eventType) {
    return null;
  }
  const message =
    typeof data.reason === 'string'
      ? data.reason
      : typeof data.message === 'string'
        ? data.message
        : typeof data.fallback_reason === 'string'
          ? data.fallback_reason
          : null;
  return {
    runId,
    eventType,
    ts: typeof data.ts === 'string' ? data.ts : new Date().toISOString(),
    message,
  };
}

function upsertExecution(
  prev: KbChatTraceStoreState,
  execution: ChatTraceExecution
): KbChatTraceStoreState {
  const executionsById = { ...(prev.executionsById ?? {}) };
  const executionOrder = [...(prev.executionOrder ?? [])];
  executionsById[execution.execution_id] = execution;
  if (!executionOrder.includes(execution.execution_id)) {
    executionOrder.push(execution.execution_id);
  }
  return {
    ...prev,
    executionsById,
    executionOrder,
  };
}

function mergeRunStateFromExecutionEvent(params: {
  prev: KbChatTraceStoreState;
  ctx: KbChatTraceReducerContext;
  runId: string;
  nodeName: string;
  status: ChatTraceExecutionStatus;
  ts: string;
  attempt?: number | null;
  message?: string | null;
  nodePath?: string[] | null;
}): ChatRunStateEvent {
  const { prev, ctx, runId, nodeName, status, ts, attempt, message, nodePath } = params;
  const baseRunState =
    prev.runState?.run_id === runId
      ? prev.runState
      : createInitialRunState(runId, ctx.totalNodes);
  if (hasAuthoritativeRunState(baseRunState)) {
    return baseRunState;
  }
  const activePath = mergeActivePath(baseRunState.active_path, nodePath ?? [nodeName]);
  const runStatus: ChatRunStateEvent['run_status'] =
    status === 'waiting_user'
      ? 'waiting_user'
      : status === 'failed'
        ? 'failed'
        : baseRunState.run_status;
  return {
    ...baseRunState,
    run_id: runId,
    run_status: runStatus,
    current_step_id: nodeName,
    current_step_label: ctx.resolveNodeLabel(nodeName),
    current_step_status: status,
    current_node: nodeName,
    attempt: typeof attempt === 'number' ? attempt : baseRunState.attempt,
    message: message ?? baseRunState.message,
    active_path: activePath,
    progress: buildProgressFromActivePath(activePath, ctx.totalNodes, runStatus),
    ts,
  };
}

const KNOWN_CUSTOM_EVENT_TYPES = new Set<string>(KB_CHAT_CUSTOM_EVENT_TYPES);

export function reduceKbChatTraceState(
  prev: KbChatTraceStoreState,
  action: KbChatTraceAction,
  ctx: KbChatTraceReducerContext
): KbChatTraceStoreState {
  if (action.type === 'meta') {
    const runId = action.runId;
    return {
      ...prev,
      runId,
      runState: prev.runState ?? createInitialRunState(runId, ctx.totalNodes),
      executionsById: prev.executionsById ?? {},
      executionOrder: prev.executionOrder ?? [],
    };
  }

  if (action.type === 'updates') {
    return {
      ...prev,
      executionsById: prev.executionsById ?? {},
      executionOrder: prev.executionOrder ?? [],
    };
  }

  if (action.type === 'step') {
    const parsedStep = parseStepEvent(action.raw);
    if (!parsedStep) {
      return {
        ...prev,
        executionsById: prev.executionsById ?? {},
        executionOrder: prev.executionOrder ?? [],
        traceWarnings: appendTraceWarning(
          prev.traceWarnings,
          'step field drift detected: missing execution_id or required fields'
        ),
      };
    }

    const current = prev.executionsById?.[parsedStep.executionId];
    const nextExecution: ChatTraceExecution = {
      execution_id: parsedStep.executionId,
      run_id: parsedStep.runId,
      node_name: parsedStep.nodeName,
      node_label: ctx.resolveNodeLabel(parsedStep.nodeName),
      status: parsedStep.status,
      started_at: current?.started_at ?? parsedStep.ts,
      updated_at: parsedStep.ts,
      ended_at: isTerminalExecutionStatus(parsedStep.status)
        ? parsedStep.ts
        : current?.ended_at ?? null,
      node_path: parsedStep.nodePath ?? current?.node_path ?? null,
      attempt: parsedStep.attempt ?? current?.attempt ?? null,
      latency_ms: current?.latency_ms ?? null,
      input_items: current?.input_items ?? null,
      output_items: current?.output_items ?? null,
      error_summary: current?.error_summary ?? null,
    };
    const nextState = upsertExecution(prev, nextExecution);
    return {
      ...nextState,
      runId: parsedStep.runId,
      runState: mergeRunStateFromExecutionEvent({
        prev,
        ctx,
        runId: parsedStep.runId,
        nodeName: parsedStep.nodeName,
        status: parsedStep.status,
        ts: parsedStep.ts,
        attempt: parsedStep.attempt,
        nodePath: parsedStep.nodePath,
      }),
    };
  }

  if (action.type === 'state') {
    const stateEvent = parseState(action.raw);
    if (!stateEvent) {
      return {
        ...prev,
        executionsById: prev.executionsById ?? {},
        executionOrder: prev.executionOrder ?? [],
      };
    }
    const previousRunState =
      prev.runState?.run_id === stateEvent.run_id ? prev.runState : undefined;
    const touchedNodes = [
      ...(stateEvent.active_path ?? []),
      stateEvent.current_step_id,
      stateEvent.current_node,
    ].filter((nodeId): nodeId is string => typeof nodeId === 'string' && nodeId.length > 0);
    const activePath = mergeActivePath(previousRunState?.active_path, touchedNodes);
    return {
      ...prev,
      runId: stateEvent.run_id,
      runState: {
        ...(previousRunState ?? {}),
        ...stateEvent,
        active_path: activePath,
        last_good_answer:
          stateEvent.last_good_answer !== undefined
            ? stateEvent.last_good_answer
            : previousRunState?.last_good_answer,
        degrade_reason:
          stateEvent.degrade_reason !== undefined
            ? stateEvent.degrade_reason
            : previousRunState?.degrade_reason,
      },
      executionsById: prev.executionsById ?? {},
      executionOrder: prev.executionOrder ?? [],
    };
  }

  if (action.type === 'ui_event') {
    const uiEvent = parseUiEvent(action.raw);
    if (!uiEvent) {
      return {
        ...prev,
        executionsById: prev.executionsById ?? {},
        executionOrder: prev.executionOrder ?? [],
      };
    }
    const baseRunState =
      prev.runState?.run_id === uiEvent.run_id
        ? prev.runState
        : createInitialRunState(uiEvent.run_id, ctx.totalNodes);
    return {
      ...prev,
      runId: uiEvent.run_id,
      runState: {
        ...baseRunState,
        run_id: uiEvent.run_id,
        last_good_answer: uiEvent.candidate_answer ?? baseRunState.last_good_answer ?? null,
        degrade_reason: uiEvent.degrade_reason ?? baseRunState.degrade_reason ?? null,
        message: uiEvent.message ?? baseRunState.message,
        ts: uiEvent.ts,
      },
      executionsById: prev.executionsById ?? {},
      executionOrder: prev.executionOrder ?? [],
    };
  }

  if (action.type === 'custom') {
    const customEvent = parseCustomEvent(action.raw);
    if (!customEvent) {
      return {
        ...prev,
        executionsById: prev.executionsById ?? {},
        executionOrder: prev.executionOrder ?? [],
        traceWarnings: appendTraceWarning(
          prev.traceWarnings,
          'custom field drift detected: missing required fields'
        ),
      };
    }

    if (customEvent.eventType === 'heartbeat') {
      return {
        ...prev,
        runId: customEvent.runId,
        runState:
          prev.runState && prev.runState.run_id === customEvent.runId
            ? { ...prev.runState, ts: customEvent.ts }
            : prev.runState,
        executionsById: prev.executionsById ?? {},
        executionOrder: prev.executionOrder ?? [],
      };
    }

    if (customEvent.eventType === 'guardrail_warning') {
      return {
        ...prev,
        runId: customEvent.runId,
        executionsById: prev.executionsById ?? {},
        executionOrder: prev.executionOrder ?? [],
        traceWarnings: appendTraceWarning(
          prev.traceWarnings,
          customEvent.message ? `guardrail warning: ${customEvent.message}` : 'guardrail warning'
        ),
      };
    }

    if (KNOWN_CUSTOM_EVENT_TYPES.has(customEvent.eventType)) {
      return {
        ...prev,
        runId: customEvent.runId,
        executionsById: prev.executionsById ?? {},
        executionOrder: prev.executionOrder ?? [],
      };
    }

    return {
      ...prev,
      runId: customEvent.runId,
      executionsById: prev.executionsById ?? {},
      executionOrder: prev.executionOrder ?? [],
      traceWarnings: appendTraceWarning(
        prev.traceWarnings,
        `unhandled custom event: ${customEvent.eventType}`
      ),
    };
  }

  const nodeEvent = parseNodeIoEvent(action.raw);
  if (!nodeEvent) {
    return {
      ...prev,
      executionsById: prev.executionsById ?? {},
      executionOrder: prev.executionOrder ?? [],
      traceWarnings: appendTraceWarning(
        prev.traceWarnings,
        'node_io field drift detected: missing required fields'
      ),
    };
  }

  if (!nodeEvent.execution_id) {
    return {
      ...prev,
      runId: nodeEvent.run_id,
      executionsById: prev.executionsById ?? {},
      executionOrder: prev.executionOrder ?? [],
      traceWarnings: appendTraceWarning(
        prev.traceWarnings,
        `node_io missing execution_id for ${nodeEvent.node_name}`
      ),
    };
  }

  const executionStatus = normalizeNodeEventStatus(nodeEvent.phase);
  const current = prev.executionsById?.[nodeEvent.execution_id];
  const nextExecution: ChatTraceExecution = {
    execution_id: nodeEvent.execution_id,
    run_id: nodeEvent.run_id,
    node_name: nodeEvent.node_name,
    node_label: ctx.resolveNodeLabel(nodeEvent.node_name),
    status: executionStatus,
    started_at: current?.started_at ?? nodeEvent.ts,
    updated_at: nodeEvent.ts,
    ended_at: isTerminalExecutionStatus(executionStatus)
      ? nodeEvent.ts
      : current?.ended_at ?? null,
    node_path: nodeEvent.node_path ?? current?.node_path ?? null,
    attempt: nodeEvent.attempt ?? current?.attempt ?? null,
    latency_ms: nodeEvent.latency_ms ?? current?.latency_ms ?? null,
    input_items: nodeEvent.display_input_items ?? current?.input_items ?? null,
    output_items: nodeEvent.display_output_items ?? current?.output_items ?? null,
    error_summary: nodeEvent.error_summary ?? current?.error_summary ?? null,
  };
  const nextState = upsertExecution(prev, nextExecution);
  return {
    ...nextState,
    runId: nodeEvent.run_id,
    runState: mergeRunStateFromExecutionEvent({
      prev,
      ctx,
      runId: nodeEvent.run_id,
      nodeName: nodeEvent.node_name,
      status: executionStatus,
      ts: nodeEvent.ts,
      attempt: nodeEvent.attempt,
      message: nodeEvent.error_summary,
      nodePath: nodeEvent.node_path,
    }),
    answerRevealReady:
      prev.answerRevealReady ||
      Boolean(
        ctx.shouldRevealAnswerOnNodeEvent && ctx.shouldRevealAnswerOnNodeEvent(nodeEvent)
      ),
  };
}

export const kbChatTraceSelectors = {
  runState: (state: KbChatTraceStoreState) => state.runState,
  traceExecutions: (state: KbChatTraceStoreState) =>
    (state.executionOrder ?? [])
      .map((executionId) => state.executionsById?.[executionId])
      .filter((execution): execution is ChatTraceExecution => Boolean(execution)),
  executionsById: (state: KbChatTraceStoreState) => state.executionsById ?? {},
  executionOrder: (state: KbChatTraceStoreState) => state.executionOrder ?? [],
  warnings: (state: KbChatTraceStoreState) => state.traceWarnings ?? [],
};

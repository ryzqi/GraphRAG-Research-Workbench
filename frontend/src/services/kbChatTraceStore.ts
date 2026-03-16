import type {
  ChatNodeDisplayItem,
  ChatNodeIoEvent,
  ChatRunStateEvent,
  ChatRunUiEvent,
} from './chats';
import { KB_CHAT_CUSTOM_EVENT_TYPES } from './chats';
import type { PipelineStep, PipelineTimelineEvent } from '../components/chat/PipelineProgress';

export interface KbChatTraceStoreState {
  runId?: string;
  runState?: ChatRunStateEvent;
  pipelineSteps?: PipelineStep[];
  nodeTimeline?: PipelineTimelineEvent[];
  nodeIoEvents?: ChatNodeIoEvent[];
  answerRevealReady?: boolean;
  traceWarnings?: string[];
}

export type KbChatTraceAction =
  | { type: 'meta'; runId: string }
  | { type: 'state'; raw: Record<string, unknown> }
  | { type: 'updates'; raw: Record<string, unknown>; ts?: string }
  | { type: 'ui_event'; raw: Record<string, unknown> }
  | { type: 'custom'; raw: Record<string, unknown> }
  | { type: 'node_io'; raw: Record<string, unknown> };

export interface KbChatTraceReducerContext {
  totalNodes: number;
  resolveNodeLabel: (nodeId: string) => string;
  shouldRevealAnswerOnNodeEvent?: (event: ChatNodeIoEvent) => boolean;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
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
  return [...current].sort((a, b) => {
    const tsCompare = (a.ts ?? '').localeCompare(b.ts ?? '');
    if (tsCompare !== 0) return tsCompare;
    return a.step_id.localeCompare(b.step_id);
  });
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

function parseUpdatesChunk(data: Record<string, unknown>): Record<string, unknown> | null {
  return asRecord(data.chunk) ?? asRecord(data);
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

function normalizePipelineStatus(status: string | null | undefined): PipelineStep['status'] | null {
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
  const phase = phaseRaw === 'start' || phaseRaw === 'end' || phaseRaw === 'error' ? phaseRaw : null;
  const nodePath =
    Array.isArray(data.node_path) && data.node_path.length > 0
      ? data.node_path.filter((item): item is string => typeof item === 'string' && item.length > 0)
      : null;
  if (!runId || !nodeName || !nodeId || !phase) {
    return null;
  }
  return {
    run_id: runId,
    node_name: nodeName,
    node_id: nodeId,
    node_path: nodePath && nodePath.length > 0 ? nodePath : null,
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

interface ParsedCustomEvent {
  runId: string;
  eventType: string;
  nodeName: string | null;
  ts: string;
  message: string | null;
  payload: Record<string, unknown>;
}

const KNOWN_CUSTOM_EVENT_TYPES = new Set<string>(KB_CHAT_CUSTOM_EVENT_TYPES);

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
  const node = asRecord(data.node);
  const nodeName =
    typeof data.node_name === 'string'
      ? data.node_name
      : typeof node?.name === 'string'
        ? node.name
        : typeof node?.id === 'string'
          ? node.id
          : null;
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
    nodeName,
    ts: typeof data.ts === 'string' ? data.ts : new Date().toISOString(),
    message,
    payload: data,
  };
}

function appendTraceWarning(
  warnings: string[] | undefined,
  warning: string
): string[] {
  return [...(warnings ?? []), warning].slice(-20);
}

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
    };
  }

  if (action.type === 'updates') {
    const chunk = parseUpdatesChunk(action.raw);
    if (!chunk) return prev;
    const touchedNodes = Object.keys(chunk).filter((nodeId) => nodeId !== '__interrupt__');
    if (touchedNodes.length === 0) return prev;
    let nextSteps = prev.pipelineSteps ?? [];
    let nextTimeline = prev.nodeTimeline;
    for (const nodeId of touchedNodes) {
      const step: PipelineStep = {
        step_id: nodeId,
        label: ctx.resolveNodeLabel(nodeId),
        status: 'completed',
        node: nodeId,
        ts: action.ts ?? new Date().toISOString(),
        meta: asRecord(chunk[nodeId]) ?? undefined,
      };
      nextSteps = upsertPipelineStep(nextSteps, step);
      nextTimeline = appendTimelineEvent(nextTimeline, {
        id: `step-${step.step_id}-${step.status}-${step.ts ?? Date.now()}`,
        source: 'step',
        step_id: step.step_id,
        label: step.label,
        node: step.node ?? null,
        status: step.status,
        run_status: null,
        attempt: typeof step.meta?.attempt === 'number' ? step.meta.attempt : null,
        message: step.message ?? null,
        io_summary: null,
        ts: step.ts ?? new Date().toISOString(),
      });
    }
    const runEnvelope = asRecord(action.raw.run);
    const runId =
      typeof action.raw.run_id === 'string'
        ? action.raw.run_id
        : typeof runEnvelope?.id === 'string'
          ? runEnvelope.id
          : prev.runId;
    const baseRunState = runId
      ? prev.runState ?? createInitialRunState(runId, ctx.totalNodes)
      : prev.runState;
    const currentNode = touchedNodes[touchedNodes.length - 1];
    const activePath = mergeActivePath(baseRunState?.active_path, touchedNodes);
    const nextRunState =
      runId && baseRunState
        ? {
            ...baseRunState,
            run_id: runId,
            run_status: (baseRunState.run_status === 'running'
              ? 'running'
              : baseRunState.run_status) as ChatRunStateEvent['run_status'],
            current_step_id: currentNode,
            current_step_label: ctx.resolveNodeLabel(currentNode),
            current_step_status: 'completed',
            current_node: currentNode,
            active_path: activePath,
            progress: buildProgressFromActivePath(
              activePath,
              ctx.totalNodes,
              baseRunState.run_status
            ),
            ts: action.ts ?? new Date().toISOString(),
          }
        : baseRunState;
    return {
      ...prev,
      runId: runId ?? prev.runId,
      runState: nextRunState,
      pipelineSteps: nextSteps,
      nodeTimeline: nextTimeline,
    };
  }

  if (action.type === 'state') {
    const stateEvent = parseState(action.raw);
    if (!stateEvent) {
      return prev;
    }
    const previousRunState =
      prev.runState?.run_id === stateEvent.run_id ? prev.runState : undefined;
    const touchedNodes = [
      ...(stateEvent.active_path ?? []),
      stateEvent.current_step_id,
      stateEvent.current_node,
    ].filter((nodeId): nodeId is string => typeof nodeId === 'string' && nodeId.length > 0);
    const activePath = mergeActivePath(previousRunState?.active_path, touchedNodes);
    const currentStepId = stateEvent.current_step_id ?? stateEvent.current_node;
    const existingStep = currentStepId
      ? (prev.pipelineSteps ?? []).find((step) => step.step_id === currentStepId)
      : undefined;
    const currentStepStatus = normalizePipelineStatus(
      stateEvent.current_step_status ?? stateEvent.run_status
    );
    const nextSteps =
      currentStepId && currentStepStatus
        ? upsertPipelineStep(prev.pipelineSteps, {
            step_id: currentStepId,
            label:
              stateEvent.current_step_label ??
              existingStep?.label ??
              ctx.resolveNodeLabel(currentStepId),
            status: currentStepStatus,
            node: stateEvent.current_node ?? existingStep?.node ?? currentStepId,
            message: stateEvent.message ?? existingStep?.message,
            ts: stateEvent.ts,
            meta:
              typeof stateEvent.attempt === 'number'
                ? { ...(existingStep?.meta ?? {}), attempt: stateEvent.attempt }
                : existingStep?.meta,
          })
        : prev.pipelineSteps;
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
      pipelineSteps: nextSteps,
      nodeTimeline: appendTimelineEvent(prev.nodeTimeline, {
        id: `state-${stateEvent.run_id}-${stateEvent.state_version ?? stateEvent.ts}`,
        source: 'state',
        step_id: currentStepId,
        label:
          stateEvent.current_step_label ??
          (currentStepId ? ctx.resolveNodeLabel(currentStepId) : stateEvent.current_node) ??
          '执行状态',
        node: stateEvent.current_node ?? currentStepId,
        status: stateEvent.current_step_status ?? stateEvent.run_status,
        run_status: stateEvent.run_status,
        attempt: stateEvent.attempt,
        message: stateEvent.message,
        ts: stateEvent.ts,
      }),
    };
  }

  if (action.type === 'ui_event') {
    const uiEvent = parseUiEvent(action.raw);
    if (!uiEvent) return prev;
    const baseRunState =
      prev.runState ?? createInitialRunState(uiEvent.run_id, ctx.totalNodes);
    const nextRunState = {
      ...baseRunState,
      run_id: uiEvent.run_id,
      last_good_answer: uiEvent.candidate_answer ?? baseRunState.last_good_answer ?? null,
      degrade_reason: uiEvent.degrade_reason ?? baseRunState.degrade_reason ?? null,
      message: uiEvent.message ?? baseRunState.message,
      ts: uiEvent.ts,
    };
    return {
      ...prev,
      runId: uiEvent.run_id,
      runState: nextRunState,
      nodeTimeline: appendTimelineEvent(prev.nodeTimeline, {
        id: `ui-${uiEvent.run_id}-${uiEvent.event_type}-${uiEvent.ts}`,
        source: 'ui',
        step_id: uiEvent.step_id ?? null,
        label: uiEvent.step_id ?? uiEvent.event_type,
        node: uiEvent.node ?? null,
        status: uiEvent.status ?? 'running',
        run_status: null,
        attempt: typeof uiEvent.meta?.attempt === 'number' ? uiEvent.meta.attempt : null,
        message: uiEvent.message ?? null,
        event_type: uiEvent.event_type,
        ts: uiEvent.ts,
      }),
    };
  }

  if (action.type === 'custom') {
    const customEvent = parseCustomEvent(action.raw);
    if (!customEvent) {
      return {
        ...prev,
        traceWarnings: appendTraceWarning(
          prev.traceWarnings,
          'custom field drift detected: missing required fields'
        ),
      };
    }

    if (customEvent.eventType === 'heartbeat') {
      return {
        ...prev,
        runId: customEvent.runId ?? prev.runId,
        runState:
          prev.runState && prev.runState.run_id === customEvent.runId
            ? { ...prev.runState, ts: customEvent.ts }
            : prev.runState,
      };
    }

    if (
      customEvent.eventType === 'answer_review_subcheck' ||
      customEvent.eventType === 'answer_review_fused'
    ) {
      const stepId = customEvent.nodeName ?? customEvent.eventType;
      const reviewStatus =
        customEvent.payload.passed === false
          ? 'failed'
          : customEvent.payload.passed === true
            ? 'completed'
            : 'running';
      return {
        ...prev,
        runId: customEvent.runId,
        nodeTimeline: appendTimelineEvent(prev.nodeTimeline, {
          id: `custom-${customEvent.runId}-${customEvent.eventType}-${customEvent.ts}`,
          source: 'ui',
          step_id: stepId,
          label: ctx.resolveNodeLabel(stepId),
          node: customEvent.nodeName,
          status: reviewStatus,
          run_status: null,
          attempt: typeof customEvent.payload.attempt === 'number' ? customEvent.payload.attempt : null,
          message: customEvent.message,
          io_summary: {
            ...customEvent.payload,
            classification: 'review_signal',
          },
          event_type: 'review_signal',
          ts: customEvent.ts,
        }),
      };
    }

    if (customEvent.eventType === 'guardrail_warning') {
      return {
        ...prev,
        runId: customEvent.runId,
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
      };
    }

    return {
      ...prev,
      runId: customEvent.runId,
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
      traceWarnings: appendTraceWarning(
        prev.traceWarnings,
        'node_io field drift detected: missing required fields'
      ),
    };
  }
  const statusFromPhase: PipelineStep['status'] =
    nodeEvent.phase === 'start'
      ? 'started'
      : nodeEvent.phase === 'error'
        ? 'failed'
        : 'completed';
  const step: PipelineStep = {
    step_id: nodeEvent.node_name,
    label: ctx.resolveNodeLabel(nodeEvent.node_name),
    status: statusFromPhase,
    node: nodeEvent.node_name,
    message: nodeEvent.error_summary ?? undefined,
    ts: nodeEvent.ts,
    meta: nodeEvent.output_summary ?? nodeEvent.input_summary ?? undefined,
  };
  const nextSteps = upsertPipelineStep(prev.pipelineSteps, step);
  const runId = nodeEvent.run_id || prev.runId;
  const baseRunState = runId
    ? prev.runState ?? createInitialRunState(runId, ctx.totalNodes)
    : prev.runState;
  const hasAuthoritativeState = Boolean(baseRunState && typeof baseRunState.state_version === 'number');
  const activePath = hasAuthoritativeState
    ? baseRunState?.active_path
    : mergeActivePath(baseRunState?.active_path, [nodeEvent.node_name]);
  const nextRunState =
    runId && baseRunState
      ? ({
          ...baseRunState,
          run_id: runId,
          current_step_id: hasAuthoritativeState ? baseRunState.current_step_id : nodeEvent.node_name,
          current_step_label: hasAuthoritativeState
            ? baseRunState.current_step_label
            : ctx.resolveNodeLabel(nodeEvent.node_name),
          current_step_status: hasAuthoritativeState ? baseRunState.current_step_status : statusFromPhase,
          current_node: hasAuthoritativeState ? baseRunState.current_node : nodeEvent.node_name,
          active_path: activePath,
          progress: hasAuthoritativeState
            ? baseRunState.progress
            : buildProgressFromActivePath(activePath, ctx.totalNodes, baseRunState.run_status),
          ts: nodeEvent.ts,
        } as ChatRunStateEvent)
      : baseRunState;
  const currentNodeIoEvents = prev.nodeIoEvents ?? [];
  const lastNodeIoEvent = currentNodeIoEvents[currentNodeIoEvents.length - 1];
  const dedupedNodeIoEvents =
    lastNodeIoEvent &&
    lastNodeIoEvent.run_id === nodeEvent.run_id &&
    lastNodeIoEvent.node_id === nodeEvent.node_id &&
    lastNodeIoEvent.phase === nodeEvent.phase &&
    lastNodeIoEvent.ts === nodeEvent.ts
      ? currentNodeIoEvents
      : [...currentNodeIoEvents, nodeEvent].slice(-240);
  return {
    ...prev,
    runId: runId ?? prev.runId,
    runState: nextRunState,
    pipelineSteps: nextSteps,
    nodeIoEvents: dedupedNodeIoEvents,
    nodeTimeline: appendTimelineEvent(prev.nodeTimeline, {
      id: `node-io-${nodeEvent.node_id}-${nodeEvent.phase}-${nodeEvent.ts}`,
      source: 'ui',
      step_id: nodeEvent.node_name,
      label: ctx.resolveNodeLabel(nodeEvent.node_name),
      node: nodeEvent.node_name,
      status: statusFromPhase,
      run_status: null,
      attempt: typeof nodeEvent.attempt === 'number' ? nodeEvent.attempt : null,
      message: nodeEvent.error_summary ?? null,
      io_summary: nodeEvent.output_summary ?? nodeEvent.input_summary ?? null,
      event_type: 'node_io',
      ts: nodeEvent.ts,
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
  pipelineSteps: (state: KbChatTraceStoreState) => state.pipelineSteps ?? [],
  nodeTimeline: (state: KbChatTraceStoreState) => state.nodeTimeline ?? [],
  nodeIoEvents: (state: KbChatTraceStoreState) => state.nodeIoEvents ?? [],
  warnings: (state: KbChatTraceStoreState) => state.traceWarnings ?? [],
};

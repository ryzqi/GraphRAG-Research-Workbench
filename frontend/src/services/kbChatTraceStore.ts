import type {
  ChatNodeDisplayItem,
  ChatNodeIoEvent,
  ChatRunStateEvent,
  ChatRunUiEvent,
} from './chats';
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
  | { type: 'updates'; raw: Record<string, unknown>; ts?: string }
  | { type: 'ui_event'; raw: Record<string, unknown> }
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

  const nodeEvent = parseNodeIoEvent(action.raw);
  if (!nodeEvent) {
    return {
      ...prev,
      traceWarnings: [
        ...(prev.traceWarnings ?? []),
        'node_io field drift detected: missing required fields',
      ].slice(-20),
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
  const activePath = mergeActivePath(baseRunState?.active_path, [nodeEvent.node_name]);
  const nextRunState =
    runId && baseRunState
      ? ({
          ...baseRunState,
          run_id: runId,
          current_step_id: nodeEvent.node_name,
          current_step_label: ctx.resolveNodeLabel(nodeEvent.node_name),
          current_step_status: statusFromPhase,
          current_node: nodeEvent.node_name,
          active_path: activePath,
          progress: buildProgressFromActivePath(activePath, ctx.totalNodes, baseRunState.run_status),
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

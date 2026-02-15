import type { ChatRunStateEvent, NormalizedChatStreamEvent } from './chats';
import type { PipelineStep, PipelineTimelineEvent } from '../components/chat/PipelineProgress';

export interface TraceStoreSnapshot {
  runId?: string;
  runState?: ChatRunStateEvent;
  pipelineSteps?: PipelineStep[];
  nodeTimeline?: PipelineTimelineEvent[];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function parseStep(payload: Record<string, unknown>): PipelineStep | null {
  const stepId = typeof payload.step_id === 'string' ? payload.step_id : null;
  const status = typeof payload.status === 'string' ? payload.status : null;
  if (!stepId || !status) {
    return null;
  }
  return {
    step_id: stepId,
    label: typeof payload.label === 'string' ? payload.label : stepId,
    status: status as PipelineStep['status'],
    node: typeof payload.node === 'string' ? payload.node : undefined,
    message: typeof payload.message === 'string' ? payload.message : undefined,
    ts: typeof payload.ts === 'string' ? payload.ts : new Date().toISOString(),
    meta: asRecord(payload.meta) ?? undefined,
  };
}

function parseState(payload: Record<string, unknown>): ChatRunStateEvent | null {
  const runId = typeof payload.run_id === 'string' ? payload.run_id : null;
  const runStatus = typeof payload.run_status === 'string' ? payload.run_status : null;
  if (!runId || !runStatus) {
    return null;
  }
  const progressRaw = asRecord(payload.progress) ?? {};
  const completed = typeof progressRaw.completed === 'number' ? progressRaw.completed : 0;
  const total = typeof progressRaw.total === 'number' ? progressRaw.total : 1;
  const percent = typeof progressRaw.percent === 'number' ? progressRaw.percent : 0;

  return {
    run_id: runId,
    run_status: runStatus as ChatRunStateEvent['run_status'],
    current_step_id: typeof payload.current_step_id === 'string' ? payload.current_step_id : null,
    current_step_label:
      typeof payload.current_step_label === 'string' ? payload.current_step_label : null,
    current_step_status:
      typeof payload.current_step_status === 'string' ? payload.current_step_status : null,
    current_node: typeof payload.current_node === 'string' ? payload.current_node : null,
    attempt: typeof payload.attempt === 'number' ? payload.attempt : null,
    message: typeof payload.message === 'string' ? payload.message : null,
    state_version: typeof payload.state_version === 'number' ? payload.state_version : undefined,
    active_path: Array.isArray(payload.active_path)
      ? payload.active_path.filter((item): item is string => typeof item === 'string')
      : undefined,
    last_good_answer:
      typeof payload.last_good_answer === 'string' ? payload.last_good_answer : undefined,
    degrade_reason: typeof payload.degrade_reason === 'string' ? payload.degrade_reason : undefined,
    progress: { completed, total, percent },
    ts: typeof payload.ts === 'string' ? payload.ts : new Date().toISOString(),
  };
}

function parseUi(payload: Record<string, unknown>) {
  const runId = typeof payload.run_id === 'string' ? payload.run_id : null;
  const eventType = typeof payload.event_type === 'string' ? payload.event_type : null;
  if (!runId || !eventType) {
    return null;
  }
  return {
    runId,
    eventType,
    stepId: typeof payload.step_id === 'string' ? payload.step_id : null,
    node: typeof payload.node === 'string' ? payload.node : null,
    status: typeof payload.status === 'string' ? payload.status : 'running',
    message: typeof payload.message === 'string' ? payload.message : null,
    ts: typeof payload.ts === 'string' ? payload.ts : new Date().toISOString(),
  };
}

function appendTimeline(
  timeline: PipelineTimelineEvent[],
  event: PipelineTimelineEvent
): PipelineTimelineEvent[] {
  const previous = timeline[timeline.length - 1];
  if (
    previous &&
    previous.source === event.source &&
    previous.step_id === event.step_id &&
    previous.node === event.node &&
    previous.status === event.status &&
    previous.message === event.message &&
    previous.event_type === event.event_type
  ) {
    return timeline;
  }
  return [...timeline, event];
}

export function createTraceStore(initial: TraceStoreSnapshot = {}) {
  let runId = initial.runId;
  let runState = initial.runState;
  let pipelineSteps = [...(initial.pipelineSteps ?? [])];
  let nodeTimeline = [...(initial.nodeTimeline ?? [])];

  const apply = (event: NormalizedChatStreamEvent) => {
    const payload = event.payload;

    if (event.event === 'meta') {
      if (typeof payload.run_id === 'string') {
        runId = payload.run_id;
      }
      return;
    }

    if (event.event === 'step') {
      const step = parseStep(payload);
      if (!step) return;
      const index = pipelineSteps.findIndex((item) => item.step_id === step.step_id);
      if (index >= 0) {
        pipelineSteps[index] = { ...pipelineSteps[index], ...step };
      } else {
        pipelineSteps.push(step);
      }
      nodeTimeline = appendTimeline(nodeTimeline, {
        id: `step-${step.step_id}-${step.status}-${step.ts}`,
        source: 'step',
        step_id: step.step_id,
        label: step.label,
        node: step.node ?? null,
        status: step.status,
        run_status: null,
        attempt: typeof step.meta?.attempt === 'number' ? step.meta.attempt : null,
        message: step.message ?? null,
        io_summary: asRecord(step.meta?.io_summary) ?? null,
        ts: step.ts ?? new Date().toISOString(),
      });
      return;
    }

    if (event.event === 'state') {
      const state = parseState(payload);
      if (!state) return;
      runId = state.run_id;
      runState = state;
      nodeTimeline = appendTimeline(nodeTimeline, {
        id: `state-${state.run_id}-${state.state_version ?? state.ts}`,
        source: 'state',
        step_id: state.current_step_id,
        label: state.current_step_label ?? state.current_node ?? 'Ö´ÐÐ×´Ì¬',
        node: state.current_node,
        status: state.current_step_status ?? state.run_status,
        run_status: state.run_status,
        attempt: state.attempt,
        message: state.message,
        ts: state.ts,
      });
      return;
    }

    if (event.event === 'ui_event') {
      const ui = parseUi(payload);
      if (!ui) return;
      runId = ui.runId;
      nodeTimeline = appendTimeline(nodeTimeline, {
        id: `ui-${ui.runId}-${ui.eventType}-${ui.ts}`,
        source: 'ui',
        step_id: ui.stepId,
        label: ui.stepId ?? ui.eventType,
        node: ui.node,
        status: ui.status,
        run_status: null,
        attempt: null,
        message: ui.message,
        event_type: ui.eventType,
        ts: ui.ts,
      });
      return;
    }

    if (event.event === 'node_trace') {
      const nodeName = typeof payload.node_name === 'string' ? payload.node_name : null;
      const phase = typeof payload.phase === 'string' ? payload.phase : null;
      const ts = typeof payload.ts === 'string' ? payload.ts : new Date().toISOString();
      if (!nodeName || !phase) return;
      const nodeId = typeof payload.node_id === 'string' ? payload.node_id : nodeName;
      nodeTimeline = appendTimeline(nodeTimeline, {
        id: `node-${nodeId}-${phase}-${ts}`,
        source: 'ui',
        step_id: nodeName,
        label: nodeName,
        node: nodeName,
        status: phase,
        run_status: null,
        attempt: null,
        message: typeof payload.error_summary === 'string' ? payload.error_summary : null,
        event_type: 'node_trace',
        io_summary:
          typeof payload.latency_ms === 'number' ? { latency_ms: payload.latency_ms } : null,
        ts,
      });
      return;
    }

    if (event.event === 'tool_trace') {
      const nodeName = typeof payload.node_name === 'string' ? payload.node_name : null;
      const toolName = typeof payload.tool_name === 'string' ? payload.tool_name : null;
      if (!nodeName || !toolName) return;
      const ts = typeof payload.ts === 'string' ? payload.ts : new Date().toISOString();
      const callIndex = typeof payload.call_index === 'number' ? payload.call_index : 0;
      const ioSummary: Record<string, unknown> = {
        tool: toolName,
      };
      if (typeof payload.input_summary === 'string') {
        ioSummary.input = payload.input_summary;
      }
      if (typeof payload.output_summary === 'string') {
        ioSummary.output = payload.output_summary;
      }
      if (typeof payload.latency_ms === 'number') {
        ioSummary.latency_ms = payload.latency_ms;
      }
      nodeTimeline = appendTimeline(nodeTimeline, {
        id: `tool-${nodeName}-${toolName}-${callIndex}-${ts}`,
        source: 'ui',
        step_id: nodeName,
        label: `${nodeName} ¡¤ ${toolName}`,
        node: nodeName,
        status: 'completed',
        run_status: null,
        attempt: null,
        message: null,
        event_type: 'tool_trace',
        io_summary: ioSummary,
        ts,
      });
    }
  };

  const snapshot = (): TraceStoreSnapshot => ({
    runId,
    runState,
    pipelineSteps,
    nodeTimeline,
  });

  return {
    apply,
    snapshot,
  };
}

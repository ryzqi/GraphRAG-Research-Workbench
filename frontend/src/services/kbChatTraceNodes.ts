import type { ChatNodeIoEvent, ChatRunStateEvent, KbGraphSchema } from './chats';
import type { PipelineStep } from '../components/chat/PipelineProgress';
import {
  KB_NODE_CATALOG,
  KB_TRACE_STAGE_META,
  resolveKbNodeOrder,
  resolveKbNodeStageId,
} from './kbNodeCatalog';
import { resolveKbNodeLabel } from './kbNodeLabels';

export type TraceNodeStatus =
  | 'idle'
  | 'running'
  | 'completed'
  | 'failed'
  | 'waiting_user'
  | 'skipped';

export type TraceStageStatus = TraceNodeStatus;

export interface TraceNodeMetric {
  label: string;
  value: string;
  tone?: 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning';
}

export interface TraceNodeViewModel {
  id: string;
  title: string;
  subtitle: string | null;
  stageId: string;
  status: TraceNodeStatus;
  isActive: boolean;
  percent: number;
  latestStep: PipelineStep | null;
  latestNodeEvent: ChatNodeIoEvent | null;
  focusNodeId: string;
  order: number;
  metrics: TraceNodeMetric[];
}

export interface TraceNodeStageGroup {
  id: string;
  title: string;
  subtitle: string;
  order: number;
  status: TraceNodeStatus;
  isActive: boolean;
  completed: number;
  total: number;
  percent: number;
  nodes: TraceNodeViewModel[];
}

export type TraceStageGroup = TraceNodeStageGroup;
export type TraceStageNode = TraceNodeViewModel;

interface TraceNodeBuildParams {
  schema?: KbGraphSchema | null;
  runState?: ChatRunStateEvent;
  pipelineSteps?: PipelineStep[];
  nodeIoEvents?: ChatNodeIoEvent[];
}

interface NodeDefinition {
  id: string;
  label: string;
  phase: string | null;
  order: number;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function eventTime(value: string | undefined): number {
  if (!value) {
    return 0;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function latestByTs<T extends { ts?: string }>(items: T[]): T | null {
  if (items.length === 0) {
    return null;
  }
  return [...items].sort((a, b) => eventTime(a.ts) - eventTime(b.ts))[items.length - 1];
}

function boolToText(value: boolean): string {
  return value ? '是' : '否';
}

function formatSeconds(value: number): string {
  return `${Math.max(0, value / 1000).toFixed(1)}s`;
}

function isTerminalStatus(status: TraceNodeStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'waiting_user' || status === 'skipped';
}

function normalizeTraceStatus(status: string | null | undefined): TraceNodeStatus | null {
  switch (status) {
    case 'running':
    case 'started':
      return 'running';
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

function resolveObservedNodeOrder(
  nodeId: string,
  fallbackOrder: number,
  schema: KbGraphSchema | null | undefined
): number {
  const catalogOrder = resolveKbNodeOrder({ nodeId, schema });
  return catalogOrder === Number.MAX_SAFE_INTEGER ? fallbackOrder : catalogOrder;
}

function resolveEnabledNodes(
  schema: KbGraphSchema | null | undefined,
  steps: PipelineStep[],
  events: ChatNodeIoEvent[]
): NodeDefinition[] {
  const nodes = new Map<string, NodeDefinition>();
  const hasSchemaNodes = Array.isArray(schema?.nodes) && schema.nodes.length > 0;

  const registerNode = (nodeId: string, phase: string | null, order: number) => {
    if (!nodeId || nodes.has(nodeId)) {
      return;
    }
    nodes.set(nodeId, {
      id: nodeId,
      label: resolveKbNodeLabel(nodeId, schema),
      phase,
      order,
    });
  };

  if (hasSchemaNodes) {
    schema?.nodes.forEach((node) => {
      registerNode(
        node.id,
        node.phase ?? null,
        typeof node.order === 'number'
          ? node.order
          : resolveKbNodeOrder({ nodeId: node.id, schema })
      );
    });
  } else {
    Object.entries(KB_NODE_CATALOG).forEach(([nodeId, meta]) => {
      registerNode(nodeId, meta.phase ?? null, meta.order);
    });
  }

  steps.forEach((step, index) => {
    registerNode(
      step.step_id,
      null,
      resolveObservedNodeOrder(step.step_id, 10_000 + index, schema)
    );
  });

  events.forEach((event, index) => {
    registerNode(
      event.node_name,
      null,
      resolveObservedNodeOrder(event.node_name, 20_000 + index, schema)
    );
  });

  return [...nodes.values()].sort((a, b) => {
    if (a.order !== b.order) {
      return a.order - b.order;
    }
    return a.id.localeCompare(b.id);
  });
}

function statusFromNode(params: {
  runState?: ChatRunStateEvent;
  nodeId: string;
  steps: PipelineStep[];
  events: ChatNodeIoEvent[];
}): TraceNodeStatus {
  const { runState, nodeId, steps, events } = params;
  const latestEvent = latestByTs(events);
  const activePath = new Set(Array.isArray(runState?.active_path) ? runState?.active_path : []);
  const hasPathHit = activePath.has(nodeId);
  const hasFailedStep = steps.some((step) => step.status === 'failed');
  const hasWaitingStep = steps.some((step) => step.status === 'waiting_user');
  const hasStartedStep = steps.some((step) => step.status === 'started');
  const hasCompletedStep = steps.some(
    (step) => step.status === 'completed' || step.status === 'skipped'
  );
  const isCurrentNode = runState?.current_step_id === nodeId || runState?.current_node === nodeId;
  const currentNodeStatus = isCurrentNode
    ? normalizeTraceStatus(runState?.current_step_status)
    : null;

  if (currentNodeStatus === 'failed' || (runState?.run_status === 'failed' && isCurrentNode)) {
    return 'failed';
  }
  if (currentNodeStatus === 'waiting_user' || (runState?.run_status === 'waiting_user' && isCurrentNode)) {
    return 'waiting_user';
  }
  if (currentNodeStatus) {
    return currentNodeStatus;
  }

  if (hasFailedStep || latestEvent?.phase === 'error') {
    return 'failed';
  }
  if (hasWaitingStep) {
    return 'waiting_user';
  }
  if (hasStartedStep || latestEvent?.phase === 'start' || (runState?.run_status === 'running' && isCurrentNode)) {
    return 'running';
  }
  if (hasCompletedStep || latestEvent?.phase === 'end') {
    return 'completed';
  }
  if (runState?.run_status === 'succeeded' && (hasPathHit || steps.length > 0 || events.length > 0)) {
    return 'completed';
  }
  if ((runState?.run_status === 'failed' || runState?.run_status === 'waiting_user') && hasPathHit) {
    return 'completed';
  }
  if (hasPathHit) {
    return 'completed';
  }
  if (runState?.run_status && runState.run_status !== 'running') {
    return 'skipped';
  }
  return 'idle';
}

function metricFromSummary(
  latestNodeEvent: ChatNodeIoEvent | null,
  latestStep: PipelineStep | null
): TraceNodeMetric[] {
  const metrics: TraceNodeMetric[] = [];
  const output = asRecord(latestNodeEvent?.output_summary);
  const input = asRecord(latestNodeEvent?.input_summary);
  const fromStep = asRecord(latestStep?.meta);
  const summary = output ?? fromStep ?? input ?? {};

  if (typeof latestNodeEvent?.latency_ms === 'number') {
    metrics.push({ label: '耗时', value: formatSeconds(latestNodeEvent.latency_ms), tone: 'info' });
  }

  const evidenceCount =
    summary.evidence_count ??
    summary.retrieval_count ??
    summary.count ??
    summary.query_count ??
    summary.query_items_count;
  if (typeof evidenceCount === 'number') {
    metrics.push({ label: '数量', value: String(evidenceCount), tone: 'primary' });
  }

  if (typeof summary.passed === 'boolean') {
    metrics.push({
      label: '通过',
      value: boolToText(summary.passed),
      tone: summary.passed ? 'success' : 'warning',
    });
  }

  if (typeof summary.attempted === 'boolean') {
    metrics.push({
      label: '已执行',
      value: boolToText(summary.attempted),
      tone: summary.attempted ? 'success' : 'warning',
    });
  }

  if (typeof summary.truncated === 'boolean') {
    metrics.push({
      label: '压缩',
      value: boolToText(summary.truncated),
      tone: summary.truncated ? 'warning' : 'success',
    });
  }

  return metrics.slice(0, 4);
}

function aggregateStageStatus(statuses: TraceNodeStatus[]): TraceNodeStatus {
  if (statuses.includes('failed')) return 'failed';
  if (statuses.includes('waiting_user')) return 'waiting_user';
  if (statuses.includes('running')) return 'running';
  if (statuses.every((status) => status === 'skipped')) return 'skipped';
  if (statuses.some((status) => status === 'completed')) return 'completed';
  return 'idle';
}

export function buildTraceStageGroups({
  schema,
  runState,
  pipelineSteps,
  nodeIoEvents,
}: TraceNodeBuildParams): TraceNodeStageGroup[] {
  const steps = pipelineSteps ?? [];
  const events = nodeIoEvents ?? [];
  const nodes = resolveEnabledNodes(schema, steps, events);
  const currentNodeId =
    (typeof runState?.current_step_id === 'string' ? runState.current_step_id : null) ??
    (typeof runState?.current_node === 'string' ? runState.current_node : null);

  const stepsByNode = new Map<string, PipelineStep[]>();
  const eventsByNode = new Map<string, ChatNodeIoEvent[]>();
  nodes.forEach((node) => {
    stepsByNode.set(node.id, []);
    eventsByNode.set(node.id, []);
  });
  steps.forEach((step) => {
    stepsByNode.get(step.step_id)?.push(step);
  });
  events.forEach((event) => {
    eventsByNode.get(event.node_name)?.push(event);
  });

  const nodeCards: TraceNodeViewModel[] = nodes.map((node) => {
    const nodeSteps = stepsByNode.get(node.id) ?? [];
    const nodeEvents = eventsByNode.get(node.id) ?? [];
    const latestStep = latestByTs(nodeSteps);
    const latestNodeEvent = latestByTs(nodeEvents);
    const status = statusFromNode({
      runState,
      nodeId: node.id,
      steps: nodeSteps,
      events: nodeEvents,
    });
    const stageId = resolveKbNodeStageId({ nodeId: node.id, phase: node.phase, schema });
    const title = resolveKbNodeLabel(node.id, schema);
    return {
      id: node.id,
      title,
      subtitle: null,
      stageId,
      status,
      isActive: status === 'running' || currentNodeId === node.id,
      percent: isTerminalStatus(status) ? 100 : status === 'running' ? 60 : 0,
      latestStep,
      latestNodeEvent,
      focusNodeId: latestNodeEvent?.node_name ?? latestStep?.step_id ?? node.id,
      order: node.order,
      metrics: metricFromSummary(latestNodeEvent, latestStep),
    };
  });

  return KB_TRACE_STAGE_META.map((stage) => {
    const stageNodes = nodeCards
      .filter((node) => node.stageId === stage.id)
      .sort((a, b) => {
        if (a.order !== b.order) {
          return a.order - b.order;
        }
        return a.id.localeCompare(b.id);
      });
    const completed = stageNodes.filter((node) => isTerminalStatus(node.status)).length;
    const total = stageNodes.length;
    const percent = total > 0 ? Math.round((completed / total) * 1000) / 10 : 0;
    const status = aggregateStageStatus(stageNodes.map((node) => node.status));
    return {
      id: stage.id,
      title: stage.title,
      subtitle: stage.subtitle,
      order: stage.order,
      status,
      isActive: stageNodes.some((node) => node.isActive),
      completed,
      total,
      percent,
      nodes: stageNodes,
    };
  });
}

export function buildTraceNodes(params: TraceNodeBuildParams): TraceNodeViewModel[] {
  return buildTraceStageGroups(params).flatMap((stage) => stage.nodes);
}

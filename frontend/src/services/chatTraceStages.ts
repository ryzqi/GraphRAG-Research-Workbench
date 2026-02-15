import type { ChatNodeIoEvent, ChatRunStateEvent, KbGraphSchema } from './chats';
import type { PipelineStep } from '../components/chat/PipelineProgress';

export type TraceStageStatus =
  | 'idle'
  | 'running'
  | 'completed'
  | 'failed'
  | 'waiting_user'
  | 'skipped';

export interface TraceStageMetric {
  label: string;
  value: string;
  tone?: 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning';
}

export interface TraceStageViewModel {
  id: string;
  title: string;
  subtitle: string;
  phase: string | null;
  status: TraceStageStatus;
  isActive: boolean;
  completed: number;
  total: number;
  percent: number;
  latestStep: PipelineStep | null;
  latestNodeEvent: ChatNodeIoEvent | null;
  metrics: TraceStageMetric[];
}

interface TraceStageBuildParams {
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

function formatMs(value: number): string {
  return `${Math.max(0, Math.round(value))}ms`;
}

function phaseLabel(phase: string | null): string {
  switch (phase) {
    case 'preprocess':
      return '预处理阶段';
    case 'retrieve':
      return '检索阶段';
    case 'judge':
      return '评估阶段';
    case 'generate':
      return '生成阶段';
    case 'verify':
      return '校验阶段';
    case 'finalize':
      return '收尾阶段';
    default:
      return '节点执行';
  }
}

function isTerminalStatus(status: TraceStageStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'waiting_user' || status === 'skipped';
}

function resolveEnabledNodes(
  schema: KbGraphSchema | null | undefined,
  steps: PipelineStep[],
  events: ChatNodeIoEvent[]
): NodeDefinition[] {
  if (schema && Array.isArray(schema.nodes) && schema.nodes.length > 0) {
    return schema.nodes
      .map((node) => ({
        id: node.id,
        label: node.label || node.id,
        phase: node.phase ?? null,
        order: typeof node.order === 'number' ? node.order : Number.MAX_SAFE_INTEGER,
      }))
      .sort((a, b) => {
        if (a.order !== b.order) {
          return a.order - b.order;
        }
        return a.id.localeCompare(b.id);
      });
  }

  const inferred = new Map<string, NodeDefinition>();
  steps.forEach((step, index) => {
    if (!step.step_id) {
      return;
    }
    if (!inferred.has(step.step_id)) {
      inferred.set(step.step_id, {
        id: step.step_id,
        label: step.label || step.step_id,
        phase: null,
        order: index,
      });
    }
  });
  events.forEach((event, index) => {
    const fallbackOrder = steps.length + index;
    if (!event.node_name) {
      return;
    }
    if (!inferred.has(event.node_name)) {
      inferred.set(event.node_name, {
        id: event.node_name,
        label: event.node_name,
        phase: null,
        order: fallbackOrder,
      });
    }
  });

  return [...inferred.values()].sort((a, b) => a.order - b.order);
}

function statusFromNode(params: {
  runState?: ChatRunStateEvent;
  nodeId: string;
  steps: PipelineStep[];
  events: ChatNodeIoEvent[];
}): TraceStageStatus {
  const { runState, nodeId, steps, events } = params;
  const latestEvent = latestByTs(events);
  const activePath = new Set(
    Array.isArray(runState?.active_path) ? runState?.active_path : []
  );
  const hasPathHit = activePath.has(nodeId);
  const hasFailedStep = steps.some((step) => step.status === 'failed');
  const hasWaitingStep = steps.some((step) => step.status === 'waiting_user');
  const hasStartedStep = steps.some((step) => step.status === 'started');
  const hasCompletedStep = steps.some(
    (step) => step.status === 'completed' || step.status === 'skipped'
  );
  const isCurrentNode = runState?.current_step_id === nodeId || runState?.current_node === nodeId;

  if (hasFailedStep || latestEvent?.phase === 'error') {
    return 'failed';
  }
  if (hasWaitingStep) {
    return 'waiting_user';
  }
  if (
    hasStartedStep ||
    latestEvent?.phase === 'start' ||
    (runState?.run_status === 'running' && isCurrentNode)
  ) {
    return 'running';
  }
  if (hasCompletedStep || latestEvent?.phase === 'end') {
    return 'completed';
  }
  if (runState?.run_status === 'failed' && isCurrentNode) {
    return 'failed';
  }
  if (runState?.run_status === 'waiting_user' && isCurrentNode) {
    return 'waiting_user';
  }
  if (runState?.run_status === 'succeeded' && (hasPathHit || steps.length > 0 || events.length > 0)) {
    return 'completed';
  }
  if (
    (runState?.run_status === 'failed' || runState?.run_status === 'waiting_user') &&
    hasPathHit
  ) {
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
): TraceStageMetric[] {
  const metrics: TraceStageMetric[] = [];
  const output = asRecord(latestNodeEvent?.output_summary);
  const input = asRecord(latestNodeEvent?.input_summary);
  const fromStep = asRecord(latestStep?.meta?.io_summary);
  const summary = output ?? fromStep ?? input ?? {};

  if (typeof latestNodeEvent?.latency_ms === 'number') {
    metrics.push({ label: '耗时', value: formatMs(latestNodeEvent.latency_ms), tone: 'info' });
  }

  const evidenceCount = summary.evidence_count ?? summary.count;
  if (typeof evidenceCount === 'number') {
    metrics.push({ label: '证据数', value: String(evidenceCount), tone: 'primary' });
  }

  const queryCount = summary.query_count ?? summary.query_items_count;
  if (typeof queryCount === 'number') {
    metrics.push({ label: '查询数', value: String(queryCount) });
  }

  if (typeof summary.rerank_applied === 'boolean') {
    metrics.push({
      label: '重排',
      value: boolToText(summary.rerank_applied),
      tone: summary.rerank_applied ? 'success' : 'warning',
    });
  }

  if (typeof summary.review_passed === 'boolean') {
    metrics.push({
      label: '答案校验',
      value: boolToText(summary.review_passed),
      tone: summary.review_passed ? 'success' : 'warning',
    });
  }

  if (typeof summary.attempted === 'boolean') {
    metrics.push({
      label: '已执行',
      value: boolToText(summary.attempted),
      tone: summary.attempted ? 'success' : 'warning',
    });
  }

  if (typeof summary.strict === 'boolean') {
    metrics.push({
      label: '严格模式',
      value: boolToText(summary.strict),
    });
  }

  return metrics.slice(0, 4);
}

export function buildTraceStages({
  schema,
  runState,
  pipelineSteps,
  nodeIoEvents,
}: TraceStageBuildParams): TraceStageViewModel[] {
  const steps = pipelineSteps ?? [];
  const events = nodeIoEvents ?? [];
  const nodes = resolveEnabledNodes(schema, steps, events);

  const stepsByNode = new Map<string, PipelineStep[]>();
  const eventsByNode = new Map<string, ChatNodeIoEvent[]>();
  for (const node of nodes) {
    stepsByNode.set(node.id, []);
    eventsByNode.set(node.id, []);
  }

  for (const step of steps) {
    if (!stepsByNode.has(step.step_id)) {
      continue;
    }
    stepsByNode.get(step.step_id)?.push(step);
  }
  for (const event of events) {
    if (!eventsByNode.has(event.node_name)) {
      continue;
    }
    eventsByNode.get(event.node_name)?.push(event);
  }

  return nodes.map((node) => {
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
    const isCurrentNode = runState?.current_step_id === node.id || runState?.current_node === node.id;
    const isActive = status === 'running' || isCurrentNode;
    const metrics = metricFromSummary(latestNodeEvent, latestStep);
    const completed = isTerminalStatus(status) ? 1 : 0;
    const total = 1;
    const percent = completed > 0 ? 100 : status === 'running' ? 60 : 0;

    return {
      id: node.id,
      title: node.label,
      subtitle: phaseLabel(node.phase),
      phase: node.phase,
      status,
      isActive,
      completed,
      total,
      percent,
      latestStep,
      latestNodeEvent,
      metrics,
    };
  });
}

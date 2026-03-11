import type { ChatNodeIoEvent, ChatRunStateEvent, KbGraphSchema } from './chats';
import type { PipelineStep } from '../components/chat/PipelineProgress';
import { resolveKbNodeLabel } from './kbNodeLabels';

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
  focusNodeId: string;
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

interface StageDefinition {
  id: string;
  title: string;
  subtitle: string;
  order: number;
}

interface NodeRuntimeSnapshot {
  node: NodeDefinition;
  stageId: string;
  status: TraceStageStatus;
  latestStep: PipelineStep | null;
  latestNodeEvent: ChatNodeIoEvent | null;
}

const STAGE_DEFINITIONS: StageDefinition[] = [
  { id: 'stage_1_preprocess', title: '阶段1 预处理', subtitle: '上下文融合与歧义处理', order: 1 },
  { id: 'stage_2_route', title: '阶段2 自适应路由', subtitle: '复杂度判定与路径选择', order: 2 },
  { id: 'stage_3_enhance', title: '阶段3 查询增强', subtitle: '拆解、扩展与检索消息准备', order: 3 },
  { id: 'stage_4_retrieve', title: '阶段4 检索', subtitle: '预算规划与检索上下文构建', order: 4 },
  { id: 'stage_5_gate', title: '阶段5 证据评估', subtitle: '并行门控与动作决策', order: 5 },
  { id: 'stage_6_answer', title: '阶段6 生成与验证', subtitle: '草稿生成、审查与回修', order: 6 },
  { id: 'stage_7_finalize', title: '阶段7 置信度收敛', subtitle: '终态收敛与可解释输出', order: 7 },
];

const NODE_TO_STAGE_ID: Record<string, StageDefinition['id']> = {
  preprocess_subgraph: 'stage_1_preprocess',
  merge_context: 'stage_1_preprocess',
  coref_rewrite: 'stage_1_preprocess',
  ambiguity_check: 'stage_1_preprocess',
  normalize_rewrite: 'stage_1_preprocess',

  complexity_classify: 'stage_2_route',
  adaptive_routing: 'stage_2_route',
  simple_path: 'stage_2_route',
  moderate_path: 'stage_2_route',
  complex_path: 'stage_2_route',
  ENABLE_MULTI_QUERY_MOD: 'stage_2_route',
  ENABLE_DECOMPOSITION: 'stage_2_route',
  ENABLE_MULTI_QUERY: 'stage_2_route',
  ENABLE_HYDE: 'stage_2_route',

  decomposition: 'stage_3_enhance',
  generate_variants_mod: 'stage_3_enhance',
  generate_variants: 'stage_3_enhance',
  entity_expand: 'stage_3_enhance',
  hyde: 'stage_3_enhance',
  prepare_messages: 'stage_3_enhance',
  preprocess_exit: 'stage_3_enhance',

  retrieval_subgraph: 'stage_4_retrieve',
  retrieval_budget_plan: 'stage_4_retrieve',
  dispatch_subqueries: 'stage_4_retrieve',
  retrieve_subquery: 'stage_4_retrieve',
  merge_subquery_context: 'stage_4_retrieve',
  retrieve: 'stage_4_retrieve',
  context_compress: 'stage_4_retrieve',
  transform_query: 'stage_4_retrieve',

  evidence_gate_subgraph: 'stage_5_gate',
  doc_gate_sufficiency: 'stage_5_gate',
  doc_gate_answerability: 'stage_5_gate',
  doc_gate_conflict: 'stage_5_gate',
  doc_gate_fuse: 'stage_5_gate',
  doc_gate_route: 'stage_5_gate',

  answer_subgraph: 'stage_6_answer',
  draft_generate: 'stage_6_answer',
  generate: 'stage_6_answer',
  answer_review_dispatch: 'stage_6_answer',
  answer_review_citation: 'stage_6_answer',
  answer_review_factual: 'stage_6_answer',
  answer_review_answerability: 'stage_6_answer',
  answer_review_fuse: 'stage_6_answer',
  answer_review: 'stage_6_answer',
  cove_check: 'stage_6_answer',
  chain_of_verification: 'stage_6_answer',
  claim_citation_check: 'stage_6_answer',
  answer_repair: 'stage_6_answer',
  answer_commit: 'stage_6_answer',

  finalize: 'stage_7_finalize',
  confidence_calibrate: 'stage_7_finalize',
  force_exit: 'stage_7_finalize',
};

const PHASE_TO_STAGE_ID: Partial<Record<string, StageDefinition['id']>> = {
  preprocess: 'stage_3_enhance',
  retrieve: 'stage_4_retrieve',
  judge: 'stage_5_gate',
  generate: 'stage_6_answer',
  verify: 'stage_6_answer',
  finalize: 'stage_7_finalize',
};

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

function isTerminalStatus(status: TraceStageStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'waiting_user' || status === 'skipped';
}

function resolveEnabledNodes(
  schema: KbGraphSchema | null | undefined,
  steps: PipelineStep[],
  events: ChatNodeIoEvent[]
): NodeDefinition[] {
  const inferred = new Map<string, NodeDefinition>();
  const registerInferredNode = (nodeId: string, order: number) => {
    if (!nodeId || inferred.has(nodeId)) {
      return;
    }
    inferred.set(nodeId, {
      id: nodeId,
      label: resolveKbNodeLabel(nodeId, schema),
      phase: null,
      order,
    });
  };

  steps.forEach((step, index) => {
    registerInferredNode(step.step_id, index);
  });
  events.forEach((event, index) => {
    registerInferredNode(event.node_name, steps.length + index);
  });

  if (schema && Array.isArray(schema.nodes) && schema.nodes.length > 0) {
    const schemaNodes = schema.nodes
      .map((node) => ({
        id: node.id,
        label: resolveKbNodeLabel(node.id, schema),
        phase: node.phase ?? null,
        order: typeof node.order === 'number' ? node.order : Number.MAX_SAFE_INTEGER,
      }))
      .sort((a, b) => {
        if (a.order !== b.order) {
          return a.order - b.order;
        }
        return a.id.localeCompare(b.id);
      });

    const schemaIds = new Set(schemaNodes.map((node) => node.id));
    const offset = schemaNodes.length;
    const inferredExtras = [...inferred.values()]
      .filter((node) => !schemaIds.has(node.id))
      .map((node, index) => ({ ...node, order: offset + index }));
    return [...schemaNodes, ...inferredExtras];
  }

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
  const activePath = new Set(Array.isArray(runState?.active_path) ? runState?.active_path : []);
  const hasPathHit = activePath.has(nodeId);
  const hasFailedStep = steps.some((step) => step.status === 'failed');
  const hasWaitingStep = steps.some((step) => step.status === 'waiting_user');
  const hasStartedStep = steps.some((step) => step.status === 'started');
  const hasCompletedStep = steps.some((step) => step.status === 'completed' || step.status === 'skipped');
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
): TraceStageMetric[] {
  const metrics: TraceStageMetric[] = [];
  const output = asRecord(latestNodeEvent?.output_summary);
  const input = asRecord(latestNodeEvent?.input_summary);
  const fromStep = asRecord(latestStep?.meta?.io_summary);
  const summary = output ?? fromStep ?? input ?? {};

  if (typeof latestNodeEvent?.latency_ms === 'number') {
    metrics.push({ label: '耗时', value: formatSeconds(latestNodeEvent.latency_ms), tone: 'info' });
  }

  const evidenceCount = summary.evidence_count ?? summary.count;
  if (typeof evidenceCount === 'number') {
    metrics.push({ label: '证据数', value: String(evidenceCount), tone: 'primary' });
  }

  const queryBundle = asRecord(summary.query_bundle);
  const messagePlan = asRecord(summary.message_plan);
  const queryCount =
    summary.query_count ??
    summary.query_bundle_items_count ??
    queryBundle?.items_count ??
    summary.query_items_count;
  if (typeof queryCount === 'number') {
    metrics.push({ label: '查询数', value: String(queryCount) });
  }

  const droppedCount =
    summary.message_plan_dropped_count ?? messagePlan?.dropped_count;
  if (typeof droppedCount === 'number') {
    metrics.push({
      label: '丢弃',
      value: String(droppedCount),
      tone: droppedCount > 0 ? 'warning' : 'success',
    });
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

function resolveStageIdForNode(nodeId: string, nodePhase: string | null): StageDefinition['id'] {
  const explicit = NODE_TO_STAGE_ID[nodeId];
  if (explicit) {
    return explicit;
  }
  if (nodePhase && PHASE_TO_STAGE_ID[nodePhase]) {
    return PHASE_TO_STAGE_ID[nodePhase] as StageDefinition['id'];
  }
  return 'stage_4_retrieve';
}

function aggregateStageStatus(params: {
  runState?: ChatRunStateEvent;
  stageOrder: number;
  currentStageOrder: number;
  statuses: TraceStageStatus[];
}): TraceStageStatus {
  const { runState, stageOrder, currentStageOrder, statuses } = params;
  if (statuses.includes('failed')) {
    return 'failed';
  }
  if (statuses.includes('waiting_user')) {
    return 'waiting_user';
  }
  if (statuses.includes('running')) {
    return 'running';
  }
  if (statuses.includes('completed')) {
    return 'completed';
  }
  if (statuses.includes('skipped')) {
    return 'skipped';
  }

  const runStatus = runState?.run_status;
  if (!runStatus || runStatus === 'running') {
    return 'idle';
  }
  if (currentStageOrder > 0) {
    if (stageOrder < currentStageOrder) {
      return 'completed';
    }
    if (stageOrder > currentStageOrder) {
      return 'skipped';
    }
    if (runStatus === 'waiting_user') {
      return 'waiting_user';
    }
    if (runStatus === 'failed' || runStatus === 'canceled') {
      return 'failed';
    }
    return 'completed';
  }
  if (runStatus === 'succeeded') {
    return 'completed';
  }
  if (runStatus === 'waiting_user') {
    return 'waiting_user';
  }
  if (runStatus === 'failed' || runStatus === 'canceled') {
    return 'failed';
  }
  return 'idle';
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
    stepsByNode.get(step.step_id)?.push(step);
  }
  for (const event of events) {
    eventsByNode.get(event.node_name)?.push(event);
  }

  const nodeSnapshots: NodeRuntimeSnapshot[] = nodes.map((node) => {
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
    return {
      node,
      stageId: resolveStageIdForNode(node.id, node.phase),
      status,
      latestStep,
      latestNodeEvent,
    };
  });

  const currentNodeId =
    (typeof runState?.current_step_id === 'string' ? runState.current_step_id : null) ??
    (typeof runState?.current_node === 'string' ? runState.current_node : null);
  const currentNode = currentNodeId ? nodes.find((node) => node.id === currentNodeId) : null;
  const currentStageId = currentNodeId
    ? resolveStageIdForNode(currentNodeId, currentNode?.phase ?? null)
    : null;
  const currentStageOrder =
    STAGE_DEFINITIONS.find((stage) => stage.id === currentStageId)?.order ?? -1;

  return STAGE_DEFINITIONS.map((stage) => {
    const entries = nodeSnapshots.filter((item) => item.stageId === stage.id);
    const latestStep = latestByTs(
      entries
        .map((item) => item.latestStep)
        .filter((item): item is PipelineStep => Boolean(item))
    );
    const latestNodeEvent = latestByTs(
      entries
        .map((item) => item.latestNodeEvent)
        .filter((item): item is ChatNodeIoEvent => Boolean(item))
    );
    const status = aggregateStageStatus({
      runState,
      stageOrder: stage.order,
      currentStageOrder,
      statuses: entries.map((item) => item.status),
    });
    const isCurrentStage = currentStageId === stage.id;
    const isActive = status === 'running' || (runState?.run_status === 'running' && isCurrentStage);
    const focusNodeId =
      latestNodeEvent?.node_name ??
      latestStep?.step_id ??
      entries[entries.length - 1]?.node.id ??
      stage.id;
    const subtitleNodeLabel =
      latestNodeEvent?.node_name ?? latestStep?.step_id ?? null;
    const subtitle = subtitleNodeLabel
      ? resolveKbNodeLabel(subtitleNodeLabel, schema)
      : stage.subtitle;
    const metrics = metricFromSummary(latestNodeEvent, latestStep);
    const completed = isTerminalStatus(status) ? 1 : 0;
    const total = 1;
    const percent = completed > 0 ? 100 : status === 'running' ? 60 : 0;

    return {
      id: stage.id,
      title: stage.title,
      subtitle,
      phase: stage.id,
      status,
      isActive,
      completed,
      total,
      percent,
      latestStep,
      latestNodeEvent,
      focusNodeId,
      metrics,
    };
  });
}

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
  summaryText: string;
  summaryTags: TraceNodeMetric[];
  stageId: string;
  status: TraceNodeStatus;
  isActive: boolean;
  percent: number;
  latestStep: PipelineStep | null;
  latestNodeEvent: ChatNodeIoEvent | null;
  focusNodeId: string;
  order: number;
}

export interface TraceNodeStageGroup {
  id: string;
  title: string;
  subtitle: string;
  summaryText: string;
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

function asNonEmptyText(value: unknown): string | null {
  return typeof value === 'string' && value.trim().length > 0 ? value.trim() : null;
}

function summarizeText(value: string | null, maxChars = 28): string | null {
  if (!value) {
    return null;
  }
  if (value.length <= maxChars) {
    return value;
  }
  return `${value.slice(0, Math.max(1, maxChars - 1)).trimEnd()}…`;
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
  runState: ChatRunStateEvent | undefined,
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
    if (Array.isArray(event.node_path)) {
      event.node_path.forEach((nodeId, pathIndex) => {
        if (typeof nodeId !== 'string' || !nodeId.trim()) {
          return;
        }
        registerNode(
          nodeId,
          null,
          resolveObservedNodeOrder(nodeId, 21_000 + index * 100 + pathIndex, schema)
        );
      });
    }
  });

  const activePath = Array.isArray(runState?.active_path) ? runState.active_path : [];
  activePath.forEach((nodeId, index) => {
    if (typeof nodeId !== 'string' || !nodeId.trim()) {
      return;
    }
    registerNode(
      nodeId,
      null,
      resolveObservedNodeOrder(nodeId, 30_000 + index, schema)
    );
  });

  [runState?.current_step_id, runState?.current_node].forEach((nodeId, index) => {
    if (typeof nodeId !== 'string' || !nodeId.trim()) {
      return;
    }
    registerNode(
      nodeId,
      null,
      resolveObservedNodeOrder(nodeId, 31_000 + index, schema)
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

interface TraceNodeSummarySource {
  summary: Record<string, unknown>;
  snapshot: Record<string, unknown>;
}

function resolveSummarySource(
  latestNodeEvent: ChatNodeIoEvent | null,
  latestStep: PipelineStep | null
): TraceNodeSummarySource {
  return {
    summary:
      asRecord(latestNodeEvent?.output_summary) ??
      asRecord(latestStep?.meta) ??
      asRecord(latestNodeEvent?.input_summary) ??
      {},
    snapshot: asRecord(latestNodeEvent?.output_snapshot) ?? {},
  };
}

function complexityLabel(value: unknown): string | null {
  switch (value) {
    case 'simple':
      return '简单';
    case 'moderate':
      return '中等';
    case 'complex':
      return '复杂';
    default:
      return null;
  }
}

function resolveEvidenceCount(summary: Record<string, unknown>): number | null {
  const value =
    summary.evidence_count ??
    summary.retrieval_count ??
    summary.count ??
    summary.query_count ??
    summary.query_items_count ??
    summary.valid_citation_count ??
    null;
  return typeof value === 'number' ? value : null;
}

function extractRoutingDecision(
  snapshot: Record<string, unknown>,
  phase: string
): Record<string, unknown> {
  const routing = asRecord(snapshot.routing_decisions);
  return asRecord(routing?.[phase]) ?? {};
}

function buildGenericSummaryText(params: {
  title: string;
  status: TraceNodeStatus;
  latestNodeEvent: ChatNodeIoEvent | null;
  latestStep: PipelineStep | null;
  runState?: ChatRunStateEvent;
}): string {
  const { title, status, latestNodeEvent, latestStep, runState } = params;
  if (status === 'failed') {
    return (
      asNonEmptyText(latestNodeEvent?.error_summary) ??
      asNonEmptyText(latestStep?.message) ??
      `${title}执行失败`
    );
  }
  if (status === 'waiting_user') {
    return asNonEmptyText(runState?.message) ?? asNonEmptyText(latestStep?.message) ?? '等待补充信息';
  }
  if (status === 'running') {
    return `正在执行${title}`;
  }
  if (status === 'completed') {
    return `已完成${title}`;
  }
  if (status === 'skipped') {
    return `${title}已跳过`;
  }
  return `等待执行${title}`;
}

function buildNodeSummaryText(params: {
  nodeId: string;
  title: string;
  status: TraceNodeStatus;
  latestNodeEvent: ChatNodeIoEvent | null;
  latestStep: PipelineStep | null;
  runState?: ChatRunStateEvent;
}): string {
  const { nodeId, title, status, latestNodeEvent, latestStep, runState } = params;
  const { summary, snapshot } = resolveSummarySource(latestNodeEvent, latestStep);
  const complexity =
    complexityLabel(summary.complexity_level) ??
    complexityLabel(snapshot.complexity_level);
  const evidenceCount = resolveEvidenceCount(summary);
  const answerText =
    asNonEmptyText(snapshot.final_answer) ??
    asNonEmptyText(snapshot.best_answer) ??
    asNonEmptyText(snapshot.draft_answer);
  const docGateDecision = extractRoutingDecision(snapshot, 'doc_gate');
  const rewrittenQuery =
    summarizeText(
      asNonEmptyText(snapshot.coref_query) ??
        asNonEmptyText(snapshot.normalized_query) ??
        asNonEmptyText(snapshot.rewrite_input_query)
    );

  switch (nodeId) {
    case 'merge_context':
      return status === 'running' ? '正在整合对话上下文' : '已合并对话上下文';
    case 'coref_rewrite':
    case 'normalize_rewrite':
    case 'transform_query':
      if (summary.rewritten === true && rewrittenQuery) {
        return `改写后问题：${rewrittenQuery}`;
      }
      if (summary.rewritten === true) {
        return '已更新问题表述';
      }
      if (summary.rewritten === false) {
        return '问题保持不变';
      }
      return buildGenericSummaryText(params);
    case 'ambiguity_check':
      if (summary.ambiguous === true) {
        return '问题存在歧义，需要先澄清';
      }
      if (summary.ambiguous === false) {
        return '问题语义明确，无需澄清';
      }
      return buildGenericSummaryText(params);
    case 'complexity_classify':
      if (complexity) {
        return `已识别为${complexity}问题`;
      }
      return status === 'running' ? '正在判定问题复杂度' : '已完成复杂度判定';
    case 'preprocess_subgraph':
      return status === 'running' ? '正在执行预处理' : '预处理阶段已完成';
    case 'retrieval_budget_plan':
      return evidenceCount !== null ? `已规划 ${evidenceCount} 路检索任务` : buildGenericSummaryText(params);
    case 'dispatch_subqueries':
      return evidenceCount !== null ? `已派发 ${evidenceCount} 个子查询` : buildGenericSummaryText(params);
    case 'retrieve_subquery':
    case 'retrieve':
      if (evidenceCount !== null) {
        return evidenceCount > 0 ? `已检索到 ${evidenceCount} 条相关内容` : '未检索到有效内容';
      }
      return status === 'running' ? '正在检索知识库内容' : buildGenericSummaryText(params);
    case 'merge_subquery_context':
      return status === 'running' ? '正在汇总子查询结果' : '已汇总子查询结果';
    case 'context_compress':
      if (summary.truncated === true) {
        return '已压缩检索上下文';
      }
      if (summary.truncated === false) {
        return '检索上下文无需压缩';
      }
      return buildGenericSummaryText(params);
    case 'doc_gate_sufficiency':
    case 'doc_gate_answerability':
    case 'doc_gate_conflict':
    case 'doc_gate_fuse':
    case 'doc_gate_route':
      if (summary.passed === true) {
        return '证据校验通过，继续生成答案';
      }
      if (summary.passed === false) {
        const action = asNonEmptyText(summary.action) ?? asNonEmptyText(docGateDecision.action);
        const nextNode = asNonEmptyText(summary.next_node) ?? asNonEmptyText(docGateDecision.next_node);
        if (action?.includes('retry') || nextNode === 'transform_query') {
          return '证据不足，进入重试';
        }
        if (action?.includes('exit') || nextNode === 'force_exit') {
          return '证据不足，准备结束本轮';
        }
        return '证据校验未通过';
      }
      return buildGenericSummaryText(params);
    case 'draft_generate':
      return answerText ? '已生成候选答案' : buildGenericSummaryText(params);
    case 'answer_review_dispatch':
      return '已开始答案审查';
    case 'answer_review_citation':
    case 'answer_review_factual':
    case 'answer_review_answerability':
    case 'answer_review_fuse':
    case 'cove_check':
    case 'chain_of_verification':
    case 'claim_citation_check':
      if (summary.passed === true) {
        return '答案审查已通过';
      }
      if (summary.passed === false) {
        return '答案审查未通过，需要修复';
      }
      return buildGenericSummaryText(params);
    case 'answer_repair':
      return answerText ? '已完成答案修复' : buildGenericSummaryText(params);
    case 'answer_commit':
    case 'answer_subgraph':
      return answerText ? '已提交候选答案' : buildGenericSummaryText(params);
    case 'confidence_calibrate':
      return '已完成答案置信度校准';
    case 'force_exit':
      return '已提前结束当前流程';
    default:
      return buildGenericSummaryText({
        title,
        status,
        latestNodeEvent,
        latestStep,
        runState,
      });
  }
}

function buildStageSummaryText(params: {
  stage: { title: string; subtitle: string };
  status: TraceNodeStatus;
  nodes: TraceNodeViewModel[];
}): string {
  const { stage, status, nodes } = params;
  const activeNode = nodes.find((node) => node.isActive);
  const latestNode =
    [...nodes]
      .filter((node) => node.status !== 'idle' && node.status !== 'skipped')
      .sort((a, b) => {
        const aTime = Math.max(eventTime(a.latestNodeEvent?.ts), eventTime(a.latestStep?.ts));
        const bTime = Math.max(eventTime(b.latestNodeEvent?.ts), eventTime(b.latestStep?.ts));
        return aTime - bTime;
      })
      .at(-1) ?? null;

  if (activeNode?.summaryText) {
    return activeNode.summaryText;
  }
  if (latestNode?.summaryText && status !== 'idle' && status !== 'skipped') {
    return latestNode.summaryText;
  }

  switch (status) {
    case 'running':
      return `正在执行${stage.title.replace(/^(阶段|步骤)\d+\s*/, '')}`;
    case 'completed':
      return `已完成${stage.title.replace(/^(阶段|步骤)\d+\s*/, '')}`;
    case 'failed':
      return `${stage.title.replace(/^(阶段|步骤)\d+\s*/, '')}失败`;
    case 'waiting_user':
      return '等待用户补充信息';
    case 'skipped':
      return '本阶段未执行';
    default:
      return '等待开始';
  }
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
  const nodes = resolveEnabledNodes(schema, runState, steps, events);
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
    const summaryText = buildNodeSummaryText({
      nodeId: node.id,
      title,
      status,
      latestNodeEvent,
      latestStep,
      runState,
    });
    return {
      id: node.id,
      title,
      subtitle: null,
      summaryText,
      summaryTags: [],
      stageId,
      status,
      isActive: status === 'running' || currentNodeId === node.id,
      percent: isTerminalStatus(status) ? 100 : status === 'running' ? 60 : 0,
      latestStep,
      latestNodeEvent,
      focusNodeId: latestNodeEvent?.node_name ?? latestStep?.step_id ?? node.id,
      order: node.order,
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
      summaryText: buildStageSummaryText({
        stage,
        status,
        nodes: stageNodes,
      }),
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

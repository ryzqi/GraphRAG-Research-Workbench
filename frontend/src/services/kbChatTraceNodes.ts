import type { ChatRunStateEvent, ChatTraceExecution, KbGraphSchema } from './chats';
import {
  KB_TRACE_STAGE_META,
  type KbTraceStageId,
  resolveKbNodeCatalogEntry,
  resolveKbNodeStageId,
  resolveKbNodeTheme,
  resolveKbSchemaNode,
} from './kbNodeCatalog';

export type TraceStageStatus =
  | 'idle'
  | 'running'
  | 'completed'
  | 'failed'
  | 'waiting_user'
  | 'skipped';

export interface TraceExecutionTimelineItem extends ChatTraceExecution {
  stageId: KbTraceStageId;
  order: number;
  summaryText: string;
  isActive: boolean;
}

export interface TraceStageSummary {
  id: KbTraceStageId;
  title: string;
  subtitle: string;
  order: number;
  status: TraceStageStatus;
  executionCount: number;
  currentNodeLabel: string | null;
  summaryText: string;
  isActive: boolean;
}

interface TraceExecutionTimelineParams {
  schema?: KbGraphSchema | null;
  runState?: ChatRunStateEvent;
  traceExecutions?: ChatTraceExecution[];
}

const TRACE_SUBGRAPH_NODE_SUFFIX = '_subgraph';

function eventTime(value: string | null | undefined): number {
  if (!value) {
    return 0;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function resolveTraceNodeBaseId(nodeId: string): string {
  const trimmedNodeId = nodeId.trim();
  if (!trimmedNodeId) {
    return '';
  }
  const separatorIndex = trimmedNodeId.indexOf(':');
  return separatorIndex >= 0 ? trimmedNodeId.slice(0, separatorIndex) : trimmedNodeId;
}

function isHiddenTraceNode(nodeId: string): boolean {
  const baseId = resolveTraceNodeBaseId(nodeId);
  return baseId.length === 0 || baseId.endsWith(TRACE_SUBGRAPH_NODE_SUFFIX);
}

function shouldDisplayTraceNode(nodeId: string, schema?: KbGraphSchema | null): boolean {
  const baseId = resolveTraceNodeBaseId(nodeId);
  if (isHiddenTraceNode(baseId)) {
    return false;
  }
  return Boolean(resolveKbSchemaNode(baseId, schema) ?? resolveKbNodeCatalogEntry(baseId));
}

function resolveCurrentVisibleNodeName(params: {
  runState?: ChatRunStateEvent;
  traceExecutions?: ChatTraceExecution[];
  schema?: KbGraphSchema | null;
}): string | null {
  const { runState, traceExecutions, schema } = params;
  const currentNodeName = resolveCurrentNodeName(runState);
  if (currentNodeName && shouldDisplayTraceNode(currentNodeName, schema)) {
    return currentNodeName;
  }

  const latestVisibleStartedExecution = [...(traceExecutions ?? [])]
    .filter(
      (execution) =>
        execution.status === 'started' && shouldDisplayTraceNode(execution.node_name, schema)
    )
    .sort((left, right) => {
      const updatedCompare = eventTime(right.updated_at) - eventTime(left.updated_at);
      if (updatedCompare !== 0) {
        return updatedCompare;
      }
      const startedCompare = eventTime(right.started_at) - eventTime(left.started_at);
      if (startedCompare !== 0) {
        return startedCompare;
      }
      return right.execution_id.localeCompare(left.execution_id);
    })
    .at(0);

  return latestVisibleStartedExecution?.node_name ?? null;
}

function normalizeStageStatus(status: string | null | undefined): TraceStageStatus | null {
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

function stringifyDetailValue(value: string | string[] | undefined): string | null {
  if (typeof value === 'string') {
    return value.trim() || null;
  }
  if (Array.isArray(value)) {
    const normalized = value
      .map((item) => item.trim())
      .filter((item) => item.length > 0);
    return normalized.length > 0 ? normalized.join('；') : null;
  }
  return null;
}

function buildExecutionSummaryText(execution: ChatTraceExecution): string {
  const primaryOutput = execution.output_items?.[0];
  if (primaryOutput) {
    const text = stringifyDetailValue(primaryOutput.value);
    if (text) {
      return `${primaryOutput.label}：${text}`;
    }
  }

  const primaryInput = execution.input_items?.[0];
  if (primaryInput) {
    const text = stringifyDetailValue(primaryInput.value);
    if (text) {
      return `${primaryInput.label}：${text}`;
    }
  }

  if (execution.status === 'failed' && execution.error_summary) {
    return execution.error_summary;
  }
  if (execution.status === 'started') {
    return `正在执行${execution.node_label}`;
  }
  if (execution.status === 'waiting_user') {
    return `等待补充${execution.node_label}`;
  }
  if (execution.status === 'skipped') {
    return `${execution.node_label}已跳过`;
  }
  return `已完成${execution.node_label}`;
}

function resolveCurrentNodeName(runState?: ChatRunStateEvent): string | null {
  if (typeof runState?.current_step_id === 'string' && runState.current_step_id.trim().length > 0) {
    return runState.current_step_id;
  }
  if (typeof runState?.current_node === 'string' && runState.current_node.trim().length > 0) {
    return runState.current_node;
  }
  return null;
}

export function buildTraceExecutionTimeline({
  schema,
  runState,
  traceExecutions,
}: TraceExecutionTimelineParams): TraceExecutionTimelineItem[] {
  const currentVisibleNodeName = resolveCurrentVisibleNodeName({
    runState,
    traceExecutions,
    schema,
  });
  return [...(traceExecutions ?? [])]
    .filter((execution) => shouldDisplayTraceNode(execution.node_name, schema))
    .sort((left, right) => {
      const startedCompare = eventTime(left.started_at) - eventTime(right.started_at);
      if (startedCompare !== 0) {
        return startedCompare;
      }
      const updatedCompare = eventTime(left.updated_at) - eventTime(right.updated_at);
      if (updatedCompare !== 0) {
        return updatedCompare;
      }
      return left.execution_id.localeCompare(right.execution_id);
    })
    .map((execution) => {
      const theme = resolveKbNodeTheme(execution.node_name, schema);
      return {
        ...execution,
        node_label: execution.node_label || theme.label,
        stageId: resolveKbNodeStageId({ nodeId: execution.node_name, schema }),
        order: theme.order,
        summaryText: buildExecutionSummaryText(execution),
        isActive: execution.status === 'started' && execution.node_name === currentVisibleNodeName,
      };
    });
}

function buildStageSummaryText(params: {
  stageTitle: string;
  status: TraceStageStatus;
  currentNodeLabel: string | null;
  executions: TraceExecutionTimelineItem[];
}): string {
  const { stageTitle, status, currentNodeLabel, executions } = params;
  if (currentNodeLabel && status === 'running') {
    return `当前节点：${currentNodeLabel}`;
  }
  const latestExecution = executions.at(-1);
  if (latestExecution?.summaryText) {
    return latestExecution.summaryText;
  }
  switch (status) {
    case 'running':
      return `正在执行${stageTitle}`;
    case 'completed':
      return `已完成${stageTitle}`;
    case 'failed':
      return `${stageTitle}失败`;
    case 'waiting_user':
      return '等待用户补充信息';
    case 'skipped':
      return `${stageTitle}已跳过`;
    default:
      return '等待开始';
  }
}

function resolveStageStatus(params: {
  stageId: KbTraceStageId;
  runState?: ChatRunStateEvent;
  executions: TraceExecutionTimelineItem[];
  currentNodeName: string | null;
  schema?: KbGraphSchema | null;
}): TraceStageStatus {
  const { stageId, runState, executions, currentNodeName, schema } = params;
  const currentStageId = currentNodeName
    ? resolveKbNodeStageId({ nodeId: currentNodeName, schema })
    : null;
  const currentStatus = normalizeStageStatus(runState?.current_step_status ?? runState?.run_status);

  if (currentStageId === stageId && currentStatus) {
    return currentStatus;
  }
  if (executions.some((execution) => execution.status === 'failed')) {
    return 'failed';
  }
  if (executions.some((execution) => execution.status === 'waiting_user')) {
    return 'waiting_user';
  }
  if (executions.some((execution) => execution.status === 'started')) {
    return 'running';
  }
  if (executions.length > 0) {
    return 'completed';
  }
  if (runState?.run_status && runState.run_status !== 'running') {
    return 'skipped';
  }
  return 'idle';
}

export function buildTraceStageSummaries({
  schema,
  runState,
  traceExecutions,
}: TraceExecutionTimelineParams): TraceStageSummary[] {
  const executionTimeline = buildTraceExecutionTimeline({ schema, runState, traceExecutions });
  const currentNodeName = resolveCurrentVisibleNodeName({
    runState,
    traceExecutions,
    schema,
  });
  const currentNodeLabel = currentNodeName ? resolveKbNodeTheme(currentNodeName, schema).label : null;

  return KB_TRACE_STAGE_META.map((stage) => {
    const executions = executionTimeline.filter((execution) => execution.stageId === stage.id);
    const stageStatus = resolveStageStatus({
      stageId: stage.id,
      runState,
      executions,
      currentNodeName,
      schema,
    });
    const stageCurrentNodeLabel =
      currentNodeName && resolveKbNodeStageId({ nodeId: currentNodeName, schema }) === stage.id
        ? currentNodeLabel
        : null;
    return {
      id: stage.id,
      title: stage.title,
      subtitle: stage.subtitle,
      order: stage.order,
      status: stageStatus,
      executionCount: executions.length,
      currentNodeLabel: stageCurrentNodeLabel,
      summaryText: buildStageSummaryText({
        stageTitle: stage.title,
        status: stageStatus,
        currentNodeLabel: stageCurrentNodeLabel,
        executions,
      }),
      isActive: stageStatus === 'running' || stageStatus === 'waiting_user',
    };
  });
}

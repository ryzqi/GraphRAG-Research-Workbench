import { useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Box,
  Chip,
  Collapse,
  IconButton,
  LinearProgress,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

import type {
  ChatNodeDisplayItem,
  ChatNodeIoEvent,
  ChatRunStateEvent,
  KbGraphSchema,
} from '../../services/chats';
import { selectKbChatFlowDetailItems } from '../../services/kbChatFlowSelectors';
import {
  buildTraceStageGroups,
  type TraceStageStatus,
} from '../../services/kbChatTraceNodes';
import { resolveKbNodeTheme } from '../../services/kbNodeCatalog';
import { resolveKbNodeLabel } from '../../services/kbNodeLabels';
import type { PipelineStep } from './PipelineProgress';

interface KbChatFlowPanelProps {
  schema: KbGraphSchema | null;
  runState?: ChatRunStateEvent;
  pipelineSteps?: PipelineStep[];
  nodeIoEvents?: ChatNodeIoEvent[];
  traceWarnings?: string[];
}

function statusLabel(status: TraceStageStatus): string {
  switch (status) {
    case 'running':
      return '进行中';
    case 'completed':
      return '已完成';
    case 'failed':
      return '失败';
    case 'waiting_user':
      return '待补充';
    case 'skipped':
      return '已跳过';
    default:
      return '待执行';
  }
}

function statusChipColor(
  status: TraceStageStatus
): 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning' {
  switch (status) {
    case 'running':
      return 'info';
    case 'completed':
      return 'success';
    case 'failed':
      return 'error';
    case 'waiting_user':
      return 'warning';
    default:
      return 'default';
  }
}

function statusBorderColor(status: TraceStageStatus): string {
  switch (status) {
    case 'running':
      return 'rgba(56, 189, 248, 0.55)';
    case 'completed':
      return 'rgba(74, 222, 128, 0.52)';
    case 'failed':
      return 'rgba(248, 113, 113, 0.55)';
    case 'waiting_user':
      return 'rgba(251, 191, 36, 0.56)';
    default:
      return 'rgba(100, 116, 139, 0.34)';
  }
}

function formatProgressLabel(status: TraceStageStatus): string {
  switch (status) {
    case 'running':
      return '执行中';
    case 'completed':
      return '已完成';
    case 'failed':
      return '失败';
    case 'waiting_user':
      return '待补充';
    case 'skipped':
      return '已跳过';
    default:
      return '待执行';
  }
}

interface NodeDetailItem {
  key: string;
  label: string;
  value: string | string[];
}

type DetailSectionKind = 'input' | 'output';

function selectKeyDetailItems(params: {
  nodeId: string;
  section: DetailSectionKind;
  items: ChatNodeDisplayItem[] | NodeDetailItem[] | null | undefined;
  event: ChatNodeIoEvent | null;
}): NodeDetailItem[] {
  return selectKbChatFlowDetailItems(params);
}

function NodeBadge({ nodeId }: { nodeId: string }) {
  const theme = resolveKbNodeTheme(nodeId);
  const Icon = theme.icon;
  return (
    <Box
      component='span'
      aria-label={theme.label}
      sx={(muiTheme) => ({
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 22,
        height: 22,
        borderRadius: 999,
        color: theme.color,
        border: `1px solid ${alpha(theme.color, muiTheme.palette.mode === 'light' ? 0.35 : 0.58)}`,
        backgroundImage: `linear-gradient(135deg, ${alpha(theme.color, muiTheme.palette.mode === 'light' ? 0.16 : 0.36)}, ${alpha(theme.color, muiTheme.palette.mode === 'light' ? 0.08 : 0.18)})`,
      })}
    >
      <Icon sx={{ fontSize: 14 }} />
    </Box>
  );
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function extractTraceCommandGoto(snapshot: Record<string, unknown>): string | null {
  const command = asRecord(snapshot.__trace_command__) ?? {};
  return typeof command.goto === 'string' ? command.goto : null;
}

function asNonEmptyText(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null;
  }
  return value.trim() ? value : null;
}

function pickText(snapshot: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const text = asNonEmptyText(snapshot[key]);
    if (text) {
      return text;
    }
  }
  return null;
}

function pickStringList(snapshot: Record<string, unknown>, ...keys: string[]): string[] | null {
  for (const key of keys) {
    const raw = snapshot[key];
    if (!Array.isArray(raw)) {
      continue;
    }
    const list = raw.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
    if (list.length > 0) {
      return list;
    }
  }
  return null;
}

function recordToLines(value: unknown): string[] | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }
  const lines = Object.entries(record)
    .map(([key, item]) => {
      if (typeof item === 'number' || typeof item === 'boolean') {
        return `${key}: ${String(item)}`;
      }
      const text = asNonEmptyText(item);
      if (text) {
        return `${key}: ${text}`;
      }
      return null;
    })
    .filter((line): line is string => Boolean(line));
  return lines.length > 0 ? lines : null;
}

function toCompactJson(value: unknown): string | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  try {
    const text = JSON.stringify(value, null, 2);
    return text && text.trim().length > 0 ? text : null;
  } catch {
    return null;
  }
}

function getContextFrame(snapshot: Record<string, unknown>): Record<string, unknown> | null {
  return asRecord(snapshot.context_frame);
}

function pickContextFrameText(snapshot: Record<string, unknown>, key: string): string | null {
  const frame = getContextFrame(snapshot);
  if (!frame) return null;
  return asNonEmptyText(frame[key]);
}

function pickContextFrameTurns(snapshot: Record<string, unknown>, key: string): string[] | null {
  const frame = getContextFrame(snapshot);
  const raw = frame?.[key];
  if (!Array.isArray(raw)) return null;
  const lines: string[] = [];
  raw.forEach((item) => {
    const record = asRecord(item);
    if (!record) return;
    const roleRaw = asNonEmptyText(record.role) ?? '';
    const role = roleRaw === 'user' ? '用户' : roleRaw === 'assistant' ? '助手' : roleRaw;
    const text = asNonEmptyText(record.text);
    if (!text) return;
    lines.push(role ? `${role}: ${text}` : text);
  });
  return lines.length > 0 ? lines : null;
}

function boolToZh(value: boolean): string {
  return value ? '是' : '否';
}

function pushDisplayItem(
  items: NodeDetailItem[],
  params: {
    key: string;
    label: string;
    value: unknown;
  }
) {
  const { key, label, value } = params;
  if (typeof value === 'boolean') {
    items.push({ key, label, value: boolToZh(value) });
    return;
  }
  if (typeof value === 'number') {
    items.push({ key, label, value: String(value) });
    return;
  }
  if (typeof value === 'string') {
    const text = asNonEmptyText(value);
    if (text) {
      items.push({ key, label, value: text });
    }
    return;
  }
  if (Array.isArray(value)) {
    const lines = value.filter((line): line is string => typeof line === 'string' && line.trim().length > 0);
    if (lines.length > 0) {
      items.push({ key, label, value: lines });
    }
  }
}

function formatQueryItems(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const lines: string[] = [];
  value.forEach((item, index) => {
    if (typeof item === 'string' && item.trim()) {
      lines.push(`${index + 1}. ${item}`);
      return;
    }
    const itemRecord = asRecord(item);
    if (!itemRecord) {
      return;
    }
    const query = asNonEmptyText(itemRecord.query);
    if (!query) {
      return;
    }
    const kind = asNonEmptyText(itemRecord.kind);
    lines.push(`${index + 1}. ${kind ? `[${kind}] ` : ''}${query}`);
  });
  return lines;
}

function summaryKeyForNode(nodeId: string): string {
  if (nodeId === 'retrieve') return 'retrieval_layer';
  if (nodeId === 'draft_generate') return 'generator';
  if (
    nodeId === 'answer_review_citation' ||
    nodeId === 'answer_review_factual' ||
    nodeId === 'answer_review_answerability' ||
    nodeId === 'answer_review_fuse'
  ) {
    return 'answer_review';
  }
  if (nodeId === 'answer_commit') return 'answer_subgraph';
  return nodeId;
}

function getStageSummary(snapshot: Record<string, unknown>, nodeId: string): Record<string, unknown> {
  const stageSummaries = asRecord(snapshot.stage_summaries);
  if (!stageSummaries) return {};
  return asRecord(stageSummaries[summaryKeyForNode(nodeId)]) ?? {};
}

function getReflection(snapshot: Record<string, unknown>): Record<string, unknown> {
  return asRecord(snapshot.reflection) ?? {};
}

function getRoutingDecision(
  snapshot: Record<string, unknown>,
  phase: string
): Record<string, unknown> {
  const routing = asRecord(snapshot.routing_decisions);
  if (!routing) return {};
  return asRecord(routing[phase]) ?? {};
}

function getRetrievalMetrics(snapshot: Record<string, unknown>): Record<string, unknown> {
  const metrics = asRecord(snapshot.metrics);
  if (!metrics) return {};
  return asRecord(metrics.retrieval_layer) ?? {};
}

function buildFallbackInputItems(
  nodeId: string,
  event: ChatNodeIoEvent | null | undefined
): NodeDetailItem[] {
  const snapshot = asRecord(event?.input_snapshot);
  if (!snapshot) {
    const summaryLines = recordToLines(event?.input_summary);
    if (!summaryLines) {
      return [];
    }
    return [{ key: 'input_summary', label: '输入摘要', value: summaryLines }];
  }
  const reflection = getReflection(snapshot);
  const items: NodeDetailItem[] = [];

  if (nodeId === 'preprocess_subgraph' || nodeId === 'merge_context') {
    pushDisplayItem(items, { key: 'user_input', label: '用户问题', value: pickText(snapshot, 'user_input') });
  } else if (nodeId === 'coref_rewrite') {
    pushDisplayItem(items, {
      key: 'query',
      label: '输入问题',
      value: pickText(snapshot, 'rewrite_input_query', 'user_input'),
    });
  } else if (['AMBIGUITY_CHECK_ENABLED', 'ambiguity_check', 'normalize_rewrite'].includes(nodeId)) {
    pushDisplayItem(items, {
      key: 'query',
      label: '输入问题',
      value: pickText(snapshot, 'coref_query', 'rewrite_input_query', 'user_input'),
    });
  } else if (
    [
      'complexity_classify',
      'generate_variants_mod',
      'decomposition',
      'generate_variants',
      'entity_expand',
      'hyde',
    ].includes(nodeId)
  ) {
    pushDisplayItem(items, {
      key: 'normalized_query',
      label: '规范化问题',
      value: pickText(snapshot, 'normalized_query', 'coref_query', 'user_input'),
    });
    pushDisplayItem(items, {
      key: 'complexity_level',
      label: '复杂度',
      value: asNonEmptyText(snapshot.complexity_level),
    });
    if (nodeId === 'entity_expand') {
      pushDisplayItem(items, {
        key: 'multi_queries',
        label: '待扩展查询',
        value: pickStringList(snapshot, 'multi_queries'),
      });
    }
  } else if (nodeId === 'prepare_messages') {
    pushDisplayItem(items, {
      key: 'normalized_query',
      label: '主问题',
      value: pickText(snapshot, 'normalized_query', 'coref_query', 'user_input'),
    });
    pushDisplayItem(items, {
      key: 'query_strategy',
      label: '消息策略',
      value: asNonEmptyText(snapshot.query_strategy),
    });
    pushDisplayItem(items, { key: 'sub_queries', label: '分解问题', value: pickStringList(snapshot, 'sub_queries') });
    pushDisplayItem(items, {
      key: 'multi_queries',
      label: '多路查询',
      value: pickStringList(snapshot, 'multi_queries'),
    });
    const hydeDocs = pickStringList(snapshot, 'hyde_docs');
    pushDisplayItem(items, { key: 'hyde_docs_count', label: 'HyDE 数量', value: hydeDocs?.length });
  } else if (nodeId === 'retrieval_subgraph' || nodeId === 'retrieve') {
    const queryItems = formatQueryItems(snapshot.query_items);
    if (queryItems.length > 0) {
      pushDisplayItem(items, { key: 'query_items', label: '检索查询项', value: queryItems });
    } else {
      pushDisplayItem(items, {
        key: 'normalized_query',
        label: '检索问题',
        value: pickText(snapshot, 'normalized_query', 'coref_query', 'user_input'),
      });
    }
  } else if (nodeId === 'retrieval_budget_plan') {
    pushDisplayItem(items, {
      key: 'complexity_level',
      label: '复杂度',
      value: asNonEmptyText(snapshot.complexity_level),
    });
    pushDisplayItem(items, {
      key: 'query_items',
      label: '查询项',
      value: formatQueryItems(snapshot.query_items),
    });
    pushDisplayItem(items, { key: 'reason', label: '历史失败原因', value: reflection.reason });
  } else if (nodeId === 'dispatch_subqueries') {
    pushDisplayItem(items, { key: 'query_strategy', label: '查询策略', value: asNonEmptyText(snapshot.query_strategy) });
    pushDisplayItem(items, { key: 'query_items', label: '查询项', value: formatQueryItems(snapshot.query_items) });
  } else if (nodeId === 'retrieve_subquery') {
    const task = asRecord(snapshot.subquery_task) ?? {};
    pushDisplayItem(items, { key: 'query', label: '分支查询', value: asNonEmptyText(task.query) });
    pushDisplayItem(items, { key: 'kind', label: '分支类型', value: asNonEmptyText(task.kind) });
  } else if (nodeId === 'merge_subquery_context') {
    pushDisplayItem(items, {
      key: 'subquery_runs_count',
      label: '分支结果数',
      value: Array.isArray(snapshot.subquery_runs) ? snapshot.subquery_runs.length : undefined,
    });
  } else if (
    ['evidence_gate_subgraph', 'doc_gate_dispatch', 'doc_gate_sufficiency', 'doc_gate_answerability', 'doc_gate_conflict', 'doc_gate_fuse', 'doc_gate_route'].includes(nodeId)
  ) {
    pushDisplayItem(items, {
      key: 'question',
      label: '待判定问题',
      value: pickText(snapshot, 'merged_context', 'normalized_query', 'user_input'),
    });
    pushDisplayItem(items, {
      key: 'final_context',
      label: '当前上下文',
      value: pickText(snapshot, 'compressed_context', 'final_context'),
    });
  } else if (nodeId === 'transform_query') {
    pushDisplayItem(items, {
      key: 'normalized_query',
      label: '当前问题',
      value: pickText(snapshot, 'normalized_query', 'coref_query', 'user_input'),
    });
    pushDisplayItem(items, { key: 'reason', label: '改写原因', value: reflection.reason });
  } else if (nodeId === 'answer_subgraph' || nodeId === 'draft_generate') {
    pushDisplayItem(items, {
      key: 'question',
      label: '待回答问题',
      value: pickText(snapshot, 'merged_context', 'user_input'),
    });
  } else if (
    nodeId === 'answer_review_citation' ||
    nodeId === 'answer_review_factual' ||
    nodeId === 'answer_review_answerability' ||
    nodeId === 'answer_review_fuse'
  ) {
    pushDisplayItem(items, {
      key: 'question',
      label: '用户问题',
      value: pickText(snapshot, 'merged_context', 'user_input'),
    });
    pushDisplayItem(items, { key: 'draft_answer', label: '待审查答案', value: pickText(snapshot, 'draft_answer') });
  } else if (nodeId === 'answer_review_dispatch') {
    pushDisplayItem(items, { key: 'draft_answer', label: '待审查答案', value: pickText(snapshot, 'draft_answer') });
  } else if (['cove_check', 'chain_of_verification', 'claim_citation_check', 'answer_commit', 'confidence_calibrate'].includes(nodeId)) {
    pushDisplayItem(items, {
      key: 'draft_answer',
      label: '答案草稿',
      value: pickText(snapshot, 'draft_answer', 'final_answer'),
    });
  } else if (nodeId === 'answer_repair') {
    pushDisplayItem(items, {
      key: 'draft_answer',
      label: '修复前答案',
      value: pickText(snapshot, 'draft_answer'),
    });
  } else if (nodeId === 'force_exit') {
    pushDisplayItem(items, { key: 'action', label: '终止动作', value: reflection.action });
    pushDisplayItem(items, { key: 'reason', label: '终止原因', value: reflection.reason });
    pushDisplayItem(items, {
      key: 'best_answer',
      label: '候选答案',
      value: pickText(snapshot, 'best_answer', 'draft_answer'),
    });
  } else if (nodeId === 'context_compress') {
    pushDisplayItem(items, {
      key: 'final_context',
      label: '压缩前上下文',
      value: pickText(snapshot, 'final_context'),
    });
  }

  if (items.length === 0) {
    pushDisplayItem(items, {
      key: 'input_summary',
      label: '输入摘要',
      value: recordToLines(event?.input_summary),
    });
    pushDisplayItem(items, {
      key: 'input_snapshot',
      label: '输入快照',
      value: toCompactJson(snapshot),
    });
  }
  return items;
}

export function buildFallbackOutputItems(
  nodeId: string,
  event: ChatNodeIoEvent | null | undefined
): NodeDetailItem[] {
  const snapshot = asRecord(event?.output_snapshot);
  const summary = snapshot ? getStageSummary(snapshot, nodeId) : {};
  const reflection = snapshot ? getReflection(snapshot) : {};
  const retrievalMetrics = snapshot ? getRetrievalMetrics(snapshot) : {};
  const items: NodeDetailItem[] = [];

  if (snapshot) {
    if (nodeId === 'preprocess_subgraph') {
      const routing = getRoutingDecision(snapshot, 'preprocess');
      pushDisplayItem(items, { key: 'next_node', label: '下一跳', value: asNonEmptyText(routing.next_node) });
      pushDisplayItem(items, { key: 'normalized_query', label: '规范化结果', value: pickText(snapshot, 'normalized_query') });
      pushDisplayItem(items, { key: 'action', label: '后续动作', value: asNonEmptyText(routing.action) });
      pushDisplayItem(items, { key: 'reason', label: '判定原因', value: asNonEmptyText(routing.reason) });
    } else if (nodeId === 'merge_context') {
      pushDisplayItem(items, {
        key: 'current_question',
        label: '用户问题',
        value: pickContextFrameText(snapshot, 'current_question') ?? pickText(snapshot, 'user_input'),
      });
      pushDisplayItem(items, {
        key: 'recent_turns',
        label: '最近对话',
        value: pickContextFrameTurns(snapshot, 'recent_turns'),
      });
      pushDisplayItem(items, {
        key: 'merged_context',
        label: '合并后上下文',
        value: pickText(snapshot, 'display_context', 'merged_context'),
      });
      pushDisplayItem(items, { key: 'memory_included', label: '是否使用记忆', value: summary.memory_included });
      pushDisplayItem(items, { key: 'summary_source', label: '摘要来源', value: summary.summary_source });
      pushDisplayItem(items, { key: 'compression_ratio', label: '压缩比', value: summary.compression_ratio });
      pushDisplayItem(items, { key: 'llm_resolve_used', label: '冲突消解', value: summary.llm_resolve_used });
      pushDisplayItem(items, { key: 'merge_fallback_used', label: '回退启发式', value: summary.fallback_used });
    } else if (nodeId === 'coref_rewrite') {
      pushDisplayItem(items, { key: 'coref_query', label: '改写后问题', value: pickText(snapshot, 'coref_query') });
      pushDisplayItem(items, { key: 'confidence', label: '消解置信度', value: summary.confidence });
      pushDisplayItem(items, { key: 'selected_mention', label: '选择候选', value: summary.selected_mention });
      pushDisplayItem(items, { key: 'rewritten', label: '是否改写', value: summary.rewritten });
      pushDisplayItem(items, { key: 'reason', label: '改写原因', value: summary.reason });
      pushDisplayItem(items, { key: 'needs_clarification_hint', label: '建议先澄清', value: summary.needs_clarification_hint });
    } else if (nodeId === 'ambiguity_check') {
      pushDisplayItem(items, { key: 'ambiguous', label: '是否歧义', value: summary.ambiguous });
      pushDisplayItem(items, { key: 'reason', label: '判定原因', value: summary.reason });
      pushDisplayItem(items, { key: 'action', label: '后续动作', value: reflection.action });
      pushDisplayItem(items, { key: 'final_answer', label: '澄清提示', value: pickText(snapshot, 'final_answer') });
    } else if (nodeId === 'normalize_rewrite') {
      pushDisplayItem(items, { key: 'normalized_query', label: '规范化结果', value: pickText(snapshot, 'normalized_query') });
      pushDisplayItem(items, { key: 'rewritten', label: '是否变化', value: summary.rewritten });
    } else if (nodeId === 'complexity_classify') {
      pushDisplayItem(items, { key: 'complexity_level', label: '复杂度等级', value: asNonEmptyText(summary.complexity_level) ?? asNonEmptyText(snapshot.complexity_level) });
      pushDisplayItem(items, { key: 'next_node', label: '下一节点', value: asNonEmptyText(summary.next_node) });
      pushDisplayItem(items, { key: 'query_strategy', label: '查询策略', value: asNonEmptyText(snapshot.query_strategy) });
      pushDisplayItem(items, { key: 'query_strategy_confidence', label: '策略置信度', value: snapshot.query_strategy_confidence });
      pushDisplayItem(items, { key: 'query_strategy_signals', label: '风险信号', value: Array.isArray(snapshot.query_strategy_signals) ? snapshot.query_strategy_signals : null });
    } else if (nodeId === 'decomposition') {
      const subQueries = pickStringList(snapshot, 'sub_queries');
      pushDisplayItem(items, { key: 'sub_queries', label: '分解问题', value: subQueries });
      pushDisplayItem(items, {
        key: 'count',
        label: '分解数量',
        value: typeof summary.count === 'number' ? summary.count : subQueries?.length,
      });
      pushDisplayItem(items, { key: 'reason', label: '分解原因', value: summary.reason });
    } else if (nodeId === 'generate_variants') {
      const multiQueries = pickStringList(snapshot, 'multi_queries');
      pushDisplayItem(items, { key: 'multi_queries', label: '多路查询', value: multiQueries });
      pushDisplayItem(items, {
        key: 'count',
        label: '查询数量',
        value: typeof summary.count === 'number' ? summary.count : multiQueries?.length,
      });
      pushDisplayItem(items, { key: 'reason', label: '处理原因', value: summary.reason });
    } else if (nodeId === 'generate_variants_mod') {
      const multiQueries = pickStringList(snapshot, 'multi_queries');
      pushDisplayItem(items, { key: 'multi_queries', label: '中等变体查询', value: multiQueries });
      pushDisplayItem(items, {
        key: 'count',
        label: '查询数量',
        value: typeof summary.count === 'number' ? summary.count : multiQueries?.length,
      });
    } else if (nodeId === 'entity_expand') {
      const multiQueries = pickStringList(snapshot, 'multi_queries');
      pushDisplayItem(items, { key: 'multi_queries', label: '多路查询', value: multiQueries });
      pushDisplayItem(items, { key: 'input_count', label: '输入数量', value: summary.input_count });
      pushDisplayItem(items, {
        key: 'expanded_count',
        label: '扩展后数量',
        value: summary.expanded_count,
      });
      pushDisplayItem(items, { key: 'added_count', label: '新增数量', value: summary.added_count });
      pushDisplayItem(items, { key: 'pruned_count', label: '剪枝数量', value: summary.pruned_count });
      pushDisplayItem(items, {
        key: 'min_confidence',
        label: '最低置信度',
        value: summary.min_confidence,
      });
      pushDisplayItem(items, {
        key: 'drift_guardrail_triggered',
        label: '漂移护栏',
        value: summary.drift_guardrail_triggered,
      });
      pushDisplayItem(items, {
        key: 'fallback_reason',
        label: '降级原因',
        value: summary.fallback_reason,
      });
      pushDisplayItem(items, { key: 'reason', label: '处理原因', value: summary.reason });
    } else if (nodeId === 'hyde') {
      pushDisplayItem(items, { key: 'enabled', label: '是否启用 HyDE', value: summary.enabled });
      pushDisplayItem(items, { key: 'hyde_doc', label: 'HyDE 生成内容', value: pickText(snapshot, 'hyde_doc') });
      pushDisplayItem(items, { key: 'reason', label: '处理原因', value: summary.reason });
    } else if (nodeId === 'prepare_messages') {
      const queryItems = formatQueryItems(snapshot.query_items);
      const messagePlan = asRecord(summary.message_plan) ?? {};
      const queryBundle = asRecord(summary.query_bundle) ?? {};
      const diagnostics = asRecord(summary.diagnostics) ?? {};
      const budget = asRecord(messagePlan.budget) ?? {};
      pushDisplayItem(items, { key: 'query_items', label: '查询项', value: queryItems });
      pushDisplayItem(items, {
        key: 'query_bundle_items_count',
        label: '入选数量',
        value: typeof queryBundle.items_count === 'number' ? queryBundle.items_count : queryItems.length,
      });
      pushDisplayItem(items, { key: 'message_plan_candidate_count', label: '候选数量', value: messagePlan.candidate_count });
      pushDisplayItem(items, { key: 'message_plan_dropped_count', label: '丢弃数量', value: messagePlan.dropped_count });
      pushDisplayItem(items, { key: 'message_plan_strategy', label: '策略', value: messagePlan.strategy });
      pushDisplayItem(items, { key: 'message_plan_max_candidates', label: '预算上限', value: budget.max_candidates });
      pushDisplayItem(items, { key: 'fallback_reason', label: '回退原因', value: diagnostics.fallback_reason });
      pushDisplayItem(items, {
        key: 'quality_signals',
        label: '质量信号',
        value: Array.isArray(diagnostics.quality_signals) ? diagnostics.quality_signals : null,
      });
      pushDisplayItem(items, {
        key: 'query_bundle_kind_breakdown',
        label: '类型分布',
        value: recordToLines(queryBundle.kind_breakdown),
      });
    } else if (nodeId === 'retrieval_subgraph') {
      pushDisplayItem(items, { key: 'evidence_count', label: '证据数量', value: retrievalMetrics.evidence_count });
      pushDisplayItem(items, { key: 'retrieval_count', label: '检索命中数', value: retrievalMetrics.retrieval_count });
      const compressionStats = asRecord(snapshot.compression_stats) ?? {};
      pushDisplayItem(items, { key: 'truncated', label: '是否压缩', value: compressionStats.truncated });
    } else if (nodeId === 'retrieval_budget_plan') {
      pushDisplayItem(items, { key: 'complexity', label: '复杂度', value: asNonEmptyText(summary.complexity) });
      pushDisplayItem(items, { key: 'query_count', label: '查询数', value: summary.query_count });
      pushDisplayItem(items, { key: 'per_query_top_k', label: '单查询 top_k', value: summary.per_query_top_k });
      pushDisplayItem(items, { key: 'global_candidates_limit', label: '全局候选上限', value: summary.global_candidates_limit });
      pushDisplayItem(items, { key: 'rerank_input_limit', label: '重排输入上限', value: summary.rerank_input_limit });
      pushDisplayItem(items, { key: 'retry_count', label: '重试次数', value: summary.retry_count });
    } else if (nodeId === 'retrieve') {
      pushDisplayItem(items, {
        key: 'evidence_count',
        label: '证据数量',
        value:
          typeof retrievalMetrics.evidence_count === 'number'
            ? retrievalMetrics.evidence_count
            : summary.evidence_count,
      });
      pushDisplayItem(items, {
        key: 'attempted',
        label: '是否执行检索',
        value:
          typeof retrievalMetrics.attempted === 'boolean'
            ? retrievalMetrics.attempted
            : summary.attempted,
      });
      pushDisplayItem(items, { key: 'reason', label: '检索说明', value: summary.reason });
      pushDisplayItem(items, {
        key: 'retrieval_count',
        label: '检索命中数',
        value:
          typeof retrievalMetrics.retrieval_count === 'number'
            ? retrievalMetrics.retrieval_count
            : summary.retrieval_count,
      });
      pushDisplayItem(items, { key: 'query_used', label: '检索查询', value: summary.query_used });
    } else if (nodeId === 'dispatch_subqueries') {
      pushDisplayItem(items, { key: 'mode', label: '编排模式', value: summary.mode });
      pushDisplayItem(items, { key: 'branch_count', label: '分支数量', value: summary.branch_count });
      pushDisplayItem(items, { key: 'rank_strategy', label: '排序策略', value: summary.rank_strategy });
      pushDisplayItem(items, { key: 'selected_queries', label: '分支查询', value: summary.selected_queries });
      pushDisplayItem(items, { key: 'reason', label: '编排原因', value: summary.reason });
    } else if (nodeId === 'retrieve_subquery') {
      const runs = Array.isArray(snapshot.subquery_runs) ? snapshot.subquery_runs : [];
      const run = asRecord(runs[0]) ?? {};
      pushDisplayItem(items, { key: 'query', label: '分支查询', value: run.query });
      pushDisplayItem(items, { key: 'kind', label: '分支类型', value: run.kind });
      pushDisplayItem(items, { key: 'retrieval_count', label: '证据数量', value: run.retrieval_count });
      pushDisplayItem(items, { key: 'success', label: '检索是否成功', value: run.success });
      pushDisplayItem(items, { key: 'reason', label: '失败原因', value: run.reason });
    } else if (nodeId === 'merge_subquery_context') {
      pushDisplayItem(items, { key: 'mode', label: '聚合模式', value: summary.mode });
      pushDisplayItem(items, { key: 'branch_count', label: '分支总数', value: summary.branch_count });
      pushDisplayItem(items, { key: 'evidence_count', label: '证据数量', value: summary.evidence_count });
      pushDisplayItem(items, { key: 'retrieval_count', label: '检索命中数', value: summary.retrieval_count });
      pushDisplayItem(items, {
        key: 'failure_reasons',
        label: '分支失败原因',
        value: recordToLines(summary.failure_reasons),
      });
    } else if (nodeId === 'context_compress') {
      const compressionStats = asRecord(snapshot.compression_stats) ?? {};
      pushDisplayItem(items, { key: 'token_limit', label: '压缩上限', value: compressionStats.token_limit });
      pushDisplayItem(items, { key: 'input_tokens', label: '压缩前 token', value: compressionStats.input_tokens });
      pushDisplayItem(items, { key: 'output_tokens', label: '压缩后 token', value: compressionStats.output_tokens });
      pushDisplayItem(items, { key: 'truncated', label: '是否截断', value: compressionStats.truncated });
    } else if (nodeId === 'evidence_gate_subgraph') {
      const routing = getRoutingDecision(snapshot, 'doc_gate');
      const routeSummary = getStageSummary(snapshot, 'doc_gate_route');
      pushDisplayItem(items, { key: 'next_node', label: '下一跳', value: asNonEmptyText(routing.next_node) });
      pushDisplayItem(items, { key: 'action', label: '后续动作', value: asNonEmptyText(routing.action) });
      pushDisplayItem(items, { key: 'reason', label: '判定原因', value: asNonEmptyText(routing.reason) });
      pushDisplayItem(items, { key: 'score', label: '门控得分', value: routing.score ?? routeSummary.score });
    } else if (nodeId === 'doc_gate_dispatch') {
      pushDisplayItem(items, { key: 'doc_gate_round', label: '门控轮次', value: snapshot.doc_gate_round });
      pushDisplayItem(items, { key: 'gates', label: '派发门控', value: ['sufficiency', 'answerability', 'conflict'] });
    } else if (['doc_gate_sufficiency', 'doc_gate_answerability', 'doc_gate_conflict'].includes(nodeId)) {
      pushDisplayItem(items, { key: 'passed', label: '是否通过', value: summary.passed });
      pushDisplayItem(items, { key: 'score', label: '评分', value: summary.score });
      pushDisplayItem(items, { key: 'reason', label: '判定原因', value: asNonEmptyText(summary.reason) });
      pushDisplayItem(items, { key: 'tokens', label: '上下文 token', value: summary.tokens });
      pushDisplayItem(items, { key: 'evidence_count', label: '证据数量', value: summary.evidence_count });
      pushDisplayItem(items, { key: 'overlap', label: '词项重叠数', value: summary.overlap });
      pushDisplayItem(items, { key: 'conflict_markers', label: '冲突标记数', value: summary.conflict_markers });
    } else if (nodeId === 'doc_gate_fuse') {
      pushDisplayItem(items, { key: 'decision', label: '融合决策', value: asNonEmptyText(summary.decision) });
      pushDisplayItem(items, { key: 'score', label: '融合得分', value: summary.score });
      pushDisplayItem(items, { key: 'missing_gates', label: '缺失门控', value: Array.isArray(summary.missing_gates) ? summary.missing_gates : null });
    } else if (nodeId === 'doc_gate_route') {
      const routing = getRoutingDecision(snapshot, 'doc_gate');
      pushDisplayItem(items, { key: 'passed', label: '相关性是否通过', value: summary.passed });
      pushDisplayItem(items, { key: 'next_node', label: '下一跳', value: asNonEmptyText(routing.next_node) });
      pushDisplayItem(items, { key: 'action', label: '后续动作', value: asNonEmptyText(routing.action) });
      pushDisplayItem(items, { key: 'reason', label: '判定原因', value: asNonEmptyText(routing.reason) });
      pushDisplayItem(items, { key: 'decision_source', label: '判定来源', value: summary.decision_source });
      pushDisplayItem(items, { key: 'confidence', label: '判定置信度', value: summary.confidence });
      pushDisplayItem(items, { key: 'evidence_score', label: '证据评分', value: summary.evidence_score });
      pushDisplayItem(items, { key: 'risk_level', label: '风险等级', value: summary.risk_level });
      pushDisplayItem(items, { key: 'retry_advice', label: '重试建议', value: summary.retry_advice });
      pushDisplayItem(items, { key: 'fallback_reason', label: '回退原因', value: summary.fallback_reason });
    } else if (nodeId === 'transform_query') {
      pushDisplayItem(items, { key: 'normalized_query', label: '改写后问题', value: pickText(snapshot, 'normalized_query') });
      pushDisplayItem(items, { key: 'rewritten', label: '是否变化', value: summary.rewritten });
      pushDisplayItem(items, { key: 'query_items', label: '改写后查询项', value: formatQueryItems(snapshot.query_items) });
    } else if (nodeId === 'answer_subgraph' || nodeId === 'answer_commit') {
      const routing = getRoutingDecision(snapshot, 'answer_subgraph');
      pushDisplayItem(items, { key: 'next_node', label: '下一跳', value: asNonEmptyText(routing.next_node) });
      pushDisplayItem(items, { key: 'action', label: '后续动作', value: asNonEmptyText(routing.action) });
      pushDisplayItem(items, { key: 'reason', label: '判定原因', value: asNonEmptyText(routing.reason) });
      pushDisplayItem(items, { key: 'degrade_reason', label: '降级原因', value: summary.degrade_reason });
      pushDisplayItem(items, { key: 'repair_attempts', label: '修复次数', value: summary.repair_attempts });
      pushDisplayItem(items, { key: 'best_answer', label: '候选答案', value: pickText(snapshot, 'best_answer', 'draft_answer') });
    } else if (nodeId === 'draft_generate') {
      pushDisplayItem(items, { key: 'draft_answer', label: '生成草稿', value: pickText(snapshot, 'draft_answer') });
      pushDisplayItem(items, { key: 'final_answer', label: '候选答案', value: pickText(snapshot, 'final_answer') });
    } else if (nodeId === 'answer_review_dispatch') {
      pushDisplayItem(items, { key: 'check_count', label: '审查数量', value: summary.check_count });
      pushDisplayItem(items, { key: 'checks', label: '审查列表', value: Array.isArray(summary.checks) ? summary.checks : null });
    } else if (
      nodeId === 'answer_review_citation' ||
      nodeId === 'answer_review_factual' ||
      nodeId === 'answer_review_answerability' ||
      nodeId === 'answer_review_fuse'
    ) {
      pushDisplayItem(items, { key: 'passed', label: '答案审查是否通过', value: summary.passed });
      pushDisplayItem(items, { key: 'action', label: '后续动作', value: reflection.action });
      pushDisplayItem(items, { key: 'reason', label: '判定原因', value: summary.reason });
      pushDisplayItem(items, { key: 'fallback_reason', label: '回退原因', value: summary.fallback_reason });
      pushDisplayItem(items, { key: 'review_risk_level', label: '审查风险等级', value: summary.review_risk_level });
      pushDisplayItem(items, { key: 'review_confidence', label: '审查置信度', value: summary.review_confidence });
      pushDisplayItem(items, { key: 'review_decision_source', label: '决策来源', value: summary.review_decision_source });
      pushDisplayItem(items, {
        key: 'review_breakdown',
        label: '子审查结果',
        value:
          typeof summary.review_breakdown === 'object' && summary.review_breakdown !== null
            ? JSON.stringify(summary.review_breakdown, null, 2)
            : undefined,
      });
      pushDisplayItem(items, { key: 'best_answer', label: '最佳答案', value: pickText(snapshot, 'best_answer') });
    } else if (nodeId === 'cove_check') {
      pushDisplayItem(items, { key: 'enabled', label: '是否启用 CoVe', value: summary.enabled });
      pushDisplayItem(items, { key: 'high_risk', label: '是否高风险', value: summary.high_risk });
    } else if (nodeId === 'chain_of_verification') {
      pushDisplayItem(items, { key: 'passed', label: '是否通过', value: summary.passed });
      pushDisplayItem(items, { key: 'reason', label: '判定原因', value: summary.reason });
      pushDisplayItem(items, { key: 'citation_count', label: '引用数', value: summary.citation_count });
    } else if (nodeId === 'claim_citation_check') {
      pushDisplayItem(items, { key: 'passed', label: '是否通过', value: summary.passed });
      pushDisplayItem(items, { key: 'reason', label: '判定原因', value: summary.reason });
      pushDisplayItem(items, { key: 'valid_citation_count', label: '有效引用数', value: summary.valid_citation_count });
      pushDisplayItem(items, { key: 'invalid_citations', label: '无效引用', value: Array.isArray(summary.invalid_citations) ? summary.invalid_citations : null });
    } else if (nodeId === 'answer_repair') {
      pushDisplayItem(items, { key: 'repair_attempt', label: '修复轮次', value: summary.repair_attempt });
      pushDisplayItem(items, { key: 'fallback_reason', label: '回退原因', value: summary.fallback_reason });
      pushDisplayItem(items, { key: 'final_answer', label: '修复后答案', value: pickText(snapshot, 'final_answer') });
    } else if (nodeId === 'confidence_calibrate') {
      pushDisplayItem(items, { key: 'confidence_score', label: '置信度分数', value: summary.confidence_score ?? snapshot.confidence_score });
      pushDisplayItem(items, { key: 'confidence_level', label: '置信度等级', value: summary.confidence_level ?? asNonEmptyText(snapshot.confidence_level) });
      pushDisplayItem(items, { key: 'gate_confidence', label: '门控置信度', value: summary.gate_confidence });
      pushDisplayItem(items, { key: 'review_confidence', label: '审查置信度', value: summary.review_confidence });
      pushDisplayItem(items, { key: 'citation_score', label: '引用得分', value: summary.citation_score });
    } else if (nodeId === 'force_exit') {
      pushDisplayItem(items, { key: 'final_answer', label: '终止输出', value: pickText(snapshot, 'final_answer') });
      pushDisplayItem(items, { key: 'reason', label: '终止原因', value: summary.reason });
      pushDisplayItem(items, { key: 'used_best_answer', label: '是否使用候选答案', value: summary.used_best_answer });
    }
  }

  if (event?.error_summary) {
    pushDisplayItem(items, { key: 'error_summary', label: '错误信息', value: event.error_summary });
  }

  if (items.length === 0) {
    pushDisplayItem(items, {
      key: 'output_summary',
      label: '输出摘要',
      value: recordToLines(event?.output_summary),
    });
    pushDisplayItem(items, {
      key: 'output_snapshot',
      label: '输出快照',
      value: toCompactJson(snapshot),
    });
  }

  return items;
}

function DetailValueBlock({
  value,
}: {
  value: string | string[];
}) {
  const [expanded, setExpanded] = useState(false);
  const text = Array.isArray(value) ? value.join('\n') : value;
  const lineCount = text.split('\n').length;
  const needsCollapse = lineCount > 6 || text.length > 320;

  return (
    <Stack spacing={0.35} sx={{ minWidth: 0 }}>
      <Typography
        variant='body2'
        sx={{
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          ...(needsCollapse && !expanded
            ? {
                display: '-webkit-box',
                WebkitLineClamp: 6,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
              }
            : null),
        }}
      >
        {text}
      </Typography>
      {needsCollapse && (
        <Button
          size='small'
          variant='text'
          onClick={() => setExpanded((prev) => !prev)}
          sx={{ px: 0, minWidth: 0, alignSelf: 'flex-start' }}
        >
          {expanded ? '收起' : '展开全文'}
        </Button>
      )}
    </Stack>
  );
}

function DetailSection({
  title,
  items,
}: {
  title: string;
  items: ChatNodeDisplayItem[] | NodeDetailItem[] | null | undefined;
}) {
  if (!items || items.length === 0) {
    return null;
  }
  return (
    <Stack spacing={0.8}>
      <Typography variant='caption' color='text.secondary'>
        {title}
      </Typography>
      <Stack spacing={0.9}>
        {items.map((item) => (
          <Box
            key={`${title}-${item.key}`}
            sx={{
              border: 1,
              borderColor: 'divider',
              borderRadius: 1.5,
              p: 1,
              bgcolor: (theme) =>
                theme.palette.mode === 'light'
                  ? alpha(theme.palette.common.black, 0.02)
                  : alpha(theme.palette.common.black, 0.16),
            }}
          >
            <Typography variant='caption' color='text.secondary' sx={{ display: 'block', mb: 0.25 }}>
              {item.label}
            </Typography>
            <DetailValueBlock value={item.value} />
          </Box>
        ))}
      </Stack>
    </Stack>
  );
}

export function KbChatFlowPanel({
  schema,
  runState,
  pipelineSteps,
  nodeIoEvents,
  traceWarnings,
}: KbChatFlowPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const stageGroups = useMemo(
    () =>
      buildTraceStageGroups({
        schema,
        runState,
        pipelineSteps,
        nodeIoEvents,
      }),
    [nodeIoEvents, pipelineSteps, runState, schema]
  );
  const nodeDetails = useMemo(
    () =>
      new Map(
        stageGroups.flatMap((stage) =>
          stage.nodes.map((node) => {
            const detailNodeId = node.focusNodeId;
            const latestNodeEvent = node.latestNodeEvent;
            const rawInputItems =
              latestNodeEvent?.display_input_items ??
              buildFallbackInputItems(detailNodeId, latestNodeEvent);
            const rawOutputItems =
              latestNodeEvent?.display_output_items ??
              buildFallbackOutputItems(detailNodeId, latestNodeEvent);
            return [
              node.id,
              {
                inputDetailItems: selectKeyDetailItems({
                  nodeId: detailNodeId,
                  section: 'input',
                  items: rawInputItems,
                  event: latestNodeEvent,
                }),
                outputDetailItems: selectKeyDetailItems({
                  nodeId: detailNodeId,
                  section: 'output',
                  items: rawOutputItems,
                  event: latestNodeEvent,
                }),
              },
            ] as const;
          })
        )
      ),
    [stageGroups]
  );

  const visibleStageGroups = stageGroups.filter((stage) => stage.nodes.length > 0);

  return (
    <Paper
      variant='outlined'
      sx={{
        p: 1.5,
        borderRadius: 3,
        height: '100%',
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        borderColor: (theme) =>
          theme.palette.mode === 'light'
            ? alpha(theme.palette.primary.main, 0.22)
            : alpha(theme.palette.primary.light, 0.3),
        bgcolor: (theme) =>
          theme.palette.mode === 'light'
            ? alpha(theme.palette.background.paper, 0.88)
            : alpha(theme.palette.background.paper, 0.44),
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
      }}
    >
      <Box sx={{ mb: 1.25 }}>
        <Typography variant='subtitle1' fontWeight={700}>
          节点执行过程
        </Typography>
      </Box>

      {Array.isArray(traceWarnings) && traceWarnings.length > 0 ? (
        <Alert severity='warning' variant='outlined' sx={{ mb: 1.25 }}>
          {traceWarnings.join('；')}
        </Alert>
      ) : null}

      <Stack
        spacing={1}
        onWheelCapture={(event) => {
          event.stopPropagation();
        }}
        onTouchMoveCapture={(event) => {
          event.stopPropagation();
        }}
        sx={{
          flex: 1,
          minHeight: 0,
          overflowX: 'hidden',
          overflowY: 'auto',
          overscrollBehaviorY: 'contain',
          WebkitOverflowScrolling: 'touch',
          scrollbarWidth: 'thin',
          scrollbarColor: (theme) =>
            `${alpha(theme.palette.primary.main, 0.42)} ${alpha(theme.palette.divider, 0.18)}`,
          '&::-webkit-scrollbar': {
            width: 10,
          },
          '&::-webkit-scrollbar-track': {
            background: 'transparent',
          },
          '&::-webkit-scrollbar-thumb': {
            borderRadius: 999,
            border: '2px solid transparent',
            backgroundClip: 'padding-box',
            backgroundColor: (theme) => alpha(theme.palette.primary.main, 0.35),
          },
          '&::-webkit-scrollbar-thumb:hover': {
            backgroundColor: (theme) => alpha(theme.palette.primary.main, 0.5),
          },
          pr: 0.25,
        }}
      >
        {visibleStageGroups.length === 0 && (
          <Paper
            variant='outlined'
            sx={{
              p: 1.5,
              borderRadius: 2,
              borderColor: (theme) => alpha(theme.palette.divider, 0.7),
              bgcolor: (theme) => alpha(theme.palette.background.default, 0.36),
            }}
          >
            <Typography variant='caption' color='text.secondary'>
              当前配置下暂无可展示节点。
            </Typography>
          </Paper>
        )}

        {visibleStageGroups.map((stage) => {
          const stageChipColor = statusChipColor(stage.status);
          return (
            <Paper
              key={stage.id}
              variant='outlined'
              sx={{
                p: 1.2,
                borderRadius: 2,
                borderColor: statusBorderColor(stage.status),
                bgcolor: (theme) =>
                  stage.isActive
                    ? alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.08 : 0.2)
                    : alpha(theme.palette.background.default, theme.palette.mode === 'light' ? 0.5 : 0.2),
                transition: 'border-color 180ms ease, background-color 180ms ease',
              }}
            >
              <Stack spacing={1}>
                <Stack direction='row' justifyContent='space-between' alignItems='center' spacing={1}>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant='body2' fontWeight={700} noWrap>
                      {stage.title}
                    </Typography>
                    <Typography variant='caption' color='text.secondary' noWrap>
                      {stage.summaryText}
                    </Typography>
                  </Box>
                  <Chip
                    size='small'
                    color={stageChipColor}
                    label={statusLabel(stage.status)}
                  />
                </Stack>

                <Stack spacing={0.45}>
                  <Stack direction='row' justifyContent='space-between'>
                    <Typography variant='caption' color='text.secondary'>
                      阶段进度
                    </Typography>
                    <Typography variant='caption' color='text.secondary'>
                      {formatProgressLabel(stage.status)}
                    </Typography>
                  </Stack>
                  <LinearProgress
                    variant='determinate'
                    value={Math.max(0, Math.min(100, stage.percent))}
                    color={stageChipColor === 'default' ? 'primary' : stageChipColor}
                    sx={{ height: 4, borderRadius: 999 }}
                  />
                </Stack>

                <Stack spacing={0.8}>
                  {stage.nodes.map((node) => {
                    const expanded = expandedId === node.id;
                    const chipColor = statusChipColor(node.status);
                    const detail = nodeDetails.get(node.id) ?? {
                      inputDetailItems: [],
                      outputDetailItems: [],
                    };
                    const { inputDetailItems, outputDetailItems } = detail;
                    return (
                      <Paper
                        key={node.id}
                        variant='outlined'
                        sx={{
                          p: 1.1,
                          borderRadius: 2,
                          borderColor: statusBorderColor(node.status),
                          bgcolor: (theme) =>
                            node.isActive
                              ? alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.06 : 0.18)
                              : alpha(theme.palette.background.paper, theme.palette.mode === 'light' ? 0.82 : 0.34),
                        }}
                      >
                        <Stack spacing={1}>
                          <Stack direction='row' justifyContent='space-between' alignItems='center' spacing={1}>
                            <Stack direction='row' spacing={0.75} alignItems='center' sx={{ minWidth: 0 }}>
                              <NodeBadge nodeId={node.focusNodeId} />
                              <Box sx={{ minWidth: 0 }}>
                                <Typography variant='body2' fontWeight={700} noWrap>
                                  {node.title}
                                </Typography>
                                <Typography variant='caption' color='text.secondary'>
                                  {node.summaryText}
                                </Typography>
                              </Box>
                            </Stack>
                            <Stack direction='row' spacing={0.5} alignItems='center'>
                              <Chip size='small' color={chipColor} label={statusLabel(node.status)} />
                              <Tooltip title={expanded ? '收起详情' : '展开详情'}>
                                <IconButton
                                  size='small'
                                  aria-label={expanded ? '收起详情' : '展开详情'}
                                  onClick={() => setExpandedId((prev) => (prev === node.id ? null : node.id))}
                                  sx={{
                                    transform: expanded ? 'rotate(180deg)' : 'none',
                                    transition: 'transform 180ms ease',
                                  }}
                                >
                                  <ExpandMoreIcon fontSize='small' />
                                </IconButton>
                              </Tooltip>
                            </Stack>
                          </Stack>

                          <Stack spacing={0.45}>
                            <Stack direction='row' justifyContent='space-between'>
                              <Typography variant='caption' color='text.secondary'>
                                节点进度
                              </Typography>
                              <Typography variant='caption' color='text.secondary'>
                                {formatProgressLabel(node.status)}
                              </Typography>
                            </Stack>
                            <LinearProgress
                              variant='determinate'
                              value={Math.max(0, Math.min(100, node.percent))}
                              color={chipColor === 'default' ? 'primary' : chipColor}
                              sx={{ height: 4, borderRadius: 999 }}
                            />
                          </Stack>
                          <Collapse in={expanded} unmountOnExit>
                            <Stack spacing={1} sx={{ pt: 0.5 }}>
                              {node.latestStep && (
                                <Typography variant='caption' color='text.secondary'>
                                  步骤：{node.latestStep.label}（{node.latestStep.status}）
                                </Typography>
                              )}
                              {node.latestNodeEvent && (
                                <Typography variant='caption' color='text.secondary'>
                                  节点：{resolveKbNodeLabel(node.latestNodeEvent.node_name, schema)}
                                  {typeof node.latestNodeEvent.attempt === 'number'
                                    ? ` · 第 ${node.latestNodeEvent.attempt} 次`
                                    : ''}
                                </Typography>
                              )}
                              {node.latestNodeEvent?.error_summary && (
                                <Typography variant='caption' color='error.main'>
                                  {node.latestNodeEvent.error_summary}
                                </Typography>
                              )}
                              {node.latestStep?.message && (
                                <Typography variant='caption' color='text.secondary'>
                                  {node.latestStep.message}
                                </Typography>
                              )}
                              <DetailSection title='关键输入' items={inputDetailItems} />
                              <DetailSection title='关键输出' items={outputDetailItems} />
                            </Stack>
                          </Collapse>
                        </Stack>
                      </Paper>
                    );
                  })}
                </Stack>
              </Stack>
            </Paper>
          );
        })}
      </Stack>
    </Paper>
  );
}

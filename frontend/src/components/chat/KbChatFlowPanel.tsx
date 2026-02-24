import { useMemo, useState, type ElementType } from 'react';
import {
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
import MergeTypeIcon from '@mui/icons-material/MergeType';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import TuneIcon from '@mui/icons-material/Tune';
import CallSplitIcon from '@mui/icons-material/CallSplit';
import ChecklistIcon from '@mui/icons-material/Checklist';
import AltRouteIcon from '@mui/icons-material/AltRoute';
import HubIcon from '@mui/icons-material/Hub';
import FactCheckIcon from '@mui/icons-material/FactCheck';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import TextSnippetIcon from '@mui/icons-material/TextSnippet';
import SearchIcon from '@mui/icons-material/Search';
import GavelIcon from '@mui/icons-material/Gavel';
import SyncAltIcon from '@mui/icons-material/SyncAlt';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import RateReviewIcon from '@mui/icons-material/RateReview';
import TaskAltIcon from '@mui/icons-material/TaskAlt';
import BlockIcon from '@mui/icons-material/Block';
import LensIcon from '@mui/icons-material/Lens';

import type {
  ChatNodeDisplayItem,
  ChatNodeIoEvent,
  ChatRunStateEvent,
  KbGraphSchema,
} from '../../services/chats';
import { selectKbChatFlowDetailItems } from '../../services/kbChatFlowSelectors';
import {
  buildTraceStages,
  type TraceStageStatus,
} from '../../services/chatTraceStages';
import type { PipelineStep } from './PipelineProgress';

interface KbChatFlowPanelProps {
  schema: KbGraphSchema | null;
  runState?: ChatRunStateEvent;
  pipelineSteps?: PipelineStep[];
  nodeIoEvents?: ChatNodeIoEvent[];
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

interface NodeBadgeTheme {
  icon: ElementType;
  label: string;
  color: string;
}

type DetailSectionKind = 'input' | 'output';

const NODE_BADGE_THEME_MAP: Record<string, NodeBadgeTheme> = {
  merge_context: { icon: MergeTypeIcon, label: '上下文合并', color: '#0EA5E9' },
  coref_rewrite: { icon: AccountTreeIcon, label: '指代消解', color: '#2563EB' },
  ambiguity_check: { icon: HelpOutlineIcon, label: '歧义判断', color: '#7C3AED' },
  normalize_rewrite: { icon: TuneIcon, label: '问题规范', color: '#4F46E5' },
  decomposition: { icon: CallSplitIcon, label: '问题分解', color: '#0284C7' },
  multi_query_check: { icon: ChecklistIcon, label: '多路判断', color: '#0284C7' },
  generate_variants: { icon: AltRouteIcon, label: '多路扩展', color: '#0D9488' },
  entity_expand: { icon: HubIcon, label: '实体扩展', color: '#059669' },
  hyde_check: { icon: FactCheckIcon, label: 'HyDE判断', color: '#16A34A' },
  hyde: { icon: AutoFixHighIcon, label: 'HyDE扩展', color: '#16A34A' },
  prepare_messages: { icon: TextSnippetIcon, label: '消息整理', color: '#65A30D' },
  retrieve: { icon: SearchIcon, label: '知识检索', color: '#CA8A04' },
  doc_grader: { icon: GavelIcon, label: '文档判定', color: '#EA580C' },
  transform_query: { icon: SyncAltIcon, label: '查询改写', color: '#DC2626' },
  generate: { icon: AutoAwesomeIcon, label: '答案生成', color: '#C026D3' },
  answer_review: { icon: RateReviewIcon, label: '答案审查', color: '#9333EA' },
  finalize: { icon: TaskAltIcon, label: '答案整理', color: '#0891B2' },
  force_exit: { icon: BlockIcon, label: '提前终止', color: '#475569' },
};

function selectKeyDetailItems(params: {
  nodeId: string;
  section: DetailSectionKind;
  items: ChatNodeDisplayItem[] | NodeDetailItem[] | null | undefined;
  event: ChatNodeIoEvent | null;
}): NodeDetailItem[] {
  return selectKbChatFlowDetailItems(params);
}

function nodeBadgeTheme(nodeId: string): NodeBadgeTheme {
  return NODE_BADGE_THEME_MAP[nodeId] ?? { icon: LensIcon, label: '节点', color: '#64748B' };
}

function NodeBadge({ nodeId }: { nodeId: string }) {
  const theme = nodeBadgeTheme(nodeId);
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
  if (nodeId === 'generate') return 'generator';
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
  if (!snapshot) return [];
  const reflection = getReflection(snapshot);
  const items: NodeDetailItem[] = [];

  if (nodeId === 'merge_context') {
    pushDisplayItem(items, { key: 'user_input', label: '用户问题', value: pickText(snapshot, 'user_input') });
  } else if (nodeId === 'coref_rewrite') {
    pushDisplayItem(items, {
      key: 'query',
      label: '输入问题',
      value: pickText(snapshot, 'rewrite_input_query', 'user_input'),
    });
  } else if (['ambiguity_check', 'normalize_rewrite'].includes(nodeId)) {
    pushDisplayItem(items, {
      key: 'query',
      label: '输入问题',
      value: pickText(snapshot, 'coref_query', 'rewrite_input_query', 'user_input'),
    });
  } else if (['decomposition', 'generate_variants', 'entity_expand', 'hyde'].includes(nodeId)) {
    pushDisplayItem(items, {
      key: 'normalized_query',
      label: '规范化问题',
      value: pickText(snapshot, 'normalized_query', 'coref_query', 'user_input'),
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
    pushDisplayItem(items, { key: 'sub_queries', label: '分解问题', value: pickStringList(snapshot, 'sub_queries') });
    pushDisplayItem(items, {
      key: 'multi_queries',
      label: '多路查询',
      value: pickStringList(snapshot, 'multi_queries'),
    });
    pushDisplayItem(items, { key: 'hyde_doc', label: 'HyDE 内容', value: pickText(snapshot, 'hyde_doc') });
  } else if (nodeId === 'retrieve') {
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
  } else if (nodeId === 'doc_grader') {
    pushDisplayItem(items, {
      key: 'question',
      label: '待判定问题',
      value: pickText(snapshot, 'merged_context', 'user_input'),
    });
  } else if (nodeId === 'transform_query') {
    pushDisplayItem(items, {
      key: 'normalized_query',
      label: '当前问题',
      value: pickText(snapshot, 'normalized_query', 'coref_query', 'user_input'),
    });
    pushDisplayItem(items, { key: 'reason', label: '改写原因', value: reflection.reason });
  } else if (nodeId === 'generate') {
    pushDisplayItem(items, {
      key: 'question',
      label: '待回答问题',
      value: pickText(snapshot, 'merged_context', 'user_input'),
    });
  } else if (nodeId === 'answer_review') {
    pushDisplayItem(items, {
      key: 'question',
      label: '用户问题',
      value: pickText(snapshot, 'merged_context', 'user_input'),
    });
    pushDisplayItem(items, { key: 'draft_answer', label: '待审查答案', value: pickText(snapshot, 'draft_answer') });
  } else if (nodeId === 'finalize') {
    pushDisplayItem(items, {
      key: 'draft_answer',
      label: '答案草稿',
      value: pickText(snapshot, 'draft_answer', 'final_answer'),
    });
  } else if (nodeId === 'force_exit') {
    pushDisplayItem(items, { key: 'action', label: '终止动作', value: reflection.action });
    pushDisplayItem(items, { key: 'reason', label: '终止原因', value: reflection.reason });
    pushDisplayItem(items, {
      key: 'best_answer',
      label: '候选答案',
      value: pickText(snapshot, 'best_answer', 'draft_answer'),
    });
  }
  return items;
}

function buildFallbackOutputItems(
  nodeId: string,
  event: ChatNodeIoEvent | null | undefined
): NodeDetailItem[] {
  const snapshot = asRecord(event?.output_snapshot);
  const summary = snapshot ? getStageSummary(snapshot, nodeId) : {};
  const reflection = snapshot ? getReflection(snapshot) : {};
  const retrievalMetrics = snapshot ? getRetrievalMetrics(snapshot) : {};
  const items: NodeDetailItem[] = [];

  if (snapshot) {
    if (nodeId === 'merge_context') {
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
    } else if (nodeId === 'decomposition') {
      const subQueries = pickStringList(snapshot, 'sub_queries');
      pushDisplayItem(items, { key: 'sub_queries', label: '分解问题', value: subQueries });
      pushDisplayItem(items, {
        key: 'count',
        label: '分解数量',
        value: typeof summary.count === 'number' ? summary.count : subQueries?.length,
      });
      pushDisplayItem(items, { key: 'reason', label: '分解原因', value: summary.reason });
    } else if (nodeId === 'generate_variants' || nodeId === 'entity_expand') {
      const multiQueries = pickStringList(snapshot, 'multi_queries');
      pushDisplayItem(items, { key: 'multi_queries', label: '多路查询', value: multiQueries });
      pushDisplayItem(items, {
        key: 'count',
        label: '查询数量',
        value: typeof summary.count === 'number' ? summary.count : multiQueries?.length,
      });
      pushDisplayItem(items, { key: 'reason', label: '处理原因', value: summary.reason });
    } else if (nodeId === 'hyde') {
      pushDisplayItem(items, { key: 'enabled', label: '是否启用 HyDE', value: summary.enabled });
      pushDisplayItem(items, { key: 'hyde_doc', label: 'HyDE 生成内容', value: pickText(snapshot, 'hyde_doc') });
      pushDisplayItem(items, { key: 'reason', label: '处理原因', value: summary.reason });
    } else if (nodeId === 'prepare_messages') {
      const queryItems = formatQueryItems(snapshot.query_items);
      pushDisplayItem(items, { key: 'query_items', label: '查询项', value: queryItems });
      pushDisplayItem(items, {
        key: 'query_items_count',
        label: '查询项数量',
        value: typeof summary.query_items_count === 'number' ? summary.query_items_count : queryItems.length,
      });
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
    } else if (nodeId === 'doc_grader') {
      pushDisplayItem(items, { key: 'passed', label: '相关性是否通过', value: summary.passed });
      pushDisplayItem(items, { key: 'action', label: '后续动作', value: reflection.action });
      pushDisplayItem(items, { key: 'reason', label: '判定原因', value: summary.reason });
      pushDisplayItem(items, { key: 'fallback_reason', label: '回退原因', value: summary.fallback_reason });
    } else if (nodeId === 'transform_query') {
      pushDisplayItem(items, { key: 'normalized_query', label: '改写后问题', value: pickText(snapshot, 'normalized_query') });
      pushDisplayItem(items, { key: 'rewritten', label: '是否变化', value: summary.rewritten });
      pushDisplayItem(items, { key: 'query_items', label: '改写后查询项', value: formatQueryItems(snapshot.query_items) });
    } else if (nodeId === 'generate') {
      pushDisplayItem(items, { key: 'draft_answer', label: '生成草稿', value: pickText(snapshot, 'draft_answer') });
      pushDisplayItem(items, { key: 'final_answer', label: '候选答案', value: pickText(snapshot, 'final_answer') });
    } else if (nodeId === 'answer_review') {
      pushDisplayItem(items, { key: 'passed', label: '答案审查是否通过', value: summary.passed });
      pushDisplayItem(items, { key: 'action', label: '后续动作', value: reflection.action });
      pushDisplayItem(items, { key: 'reason', label: '判定原因', value: summary.reason });
      pushDisplayItem(items, { key: 'fallback_reason', label: '回退原因', value: summary.fallback_reason });
      pushDisplayItem(items, { key: 'best_answer', label: '最佳答案', value: pickText(snapshot, 'best_answer') });
    } else if (nodeId === 'finalize') {
      pushDisplayItem(items, { key: 'final_answer', label: '最终答案', value: pickText(snapshot, 'final_answer') });
    } else if (nodeId === 'force_exit') {
      pushDisplayItem(items, { key: 'final_answer', label: '终止输出', value: pickText(snapshot, 'final_answer') });
      pushDisplayItem(items, { key: 'reason', label: '终止原因', value: summary.reason });
      pushDisplayItem(items, { key: 'used_best_answer', label: '是否使用候选答案', value: summary.used_best_answer });
    }
  }

  if (event?.error_summary) {
    pushDisplayItem(items, { key: 'error_summary', label: '错误信息', value: event.error_summary });
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
}: KbChatFlowPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const stages = useMemo(
    () =>
      buildTraceStages({
        schema,
        runState,
        pipelineSteps,
        nodeIoEvents,
      }),
    [nodeIoEvents, pipelineSteps, runState, schema]
  );
  const stageDetails = useMemo(
    () =>
      new Map(
        stages.map((stage) => {
          const rawInputItems =
            stage.latestNodeEvent?.display_input_items ??
            buildFallbackInputItems(stage.id, stage.latestNodeEvent);
          const rawOutputItems =
            stage.latestNodeEvent?.display_output_items ??
            buildFallbackOutputItems(stage.id, stage.latestNodeEvent);
          return [
            stage.id,
            {
              inputDetailItems: selectKeyDetailItems({
                nodeId: stage.id,
                section: 'input',
                items: rawInputItems,
                event: stage.latestNodeEvent,
              }),
              outputDetailItems: selectKeyDetailItems({
                nodeId: stage.id,
                section: 'output',
                items: rawOutputItems,
                event: stage.latestNodeEvent,
              }),
            },
          ] as const;
        })
      ),
    [stages]
  );

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
        {stages.length === 0 && (
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

        {stages.map((stage) => {
          const expanded = expandedId === stage.id;
          const chipColor = statusChipColor(stage.status);
          const detail = stageDetails.get(stage.id) ?? {
            inputDetailItems: [],
            outputDetailItems: [],
          };
          const { inputDetailItems, outputDetailItems } = detail;
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
                    : alpha(
                        theme.palette.background.default,
                        theme.palette.mode === 'light' ? 0.5 : 0.2
                      ),
                transition: 'border-color 180ms ease, background-color 180ms ease',
              }}
            >
              <Stack spacing={1}>
                <Stack direction='row' justifyContent='space-between' alignItems='center' spacing={1}>
                  <Stack direction='row' spacing={0.75} alignItems='center' sx={{ minWidth: 0 }}>
                    <NodeBadge nodeId={stage.id} />
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant='body2' fontWeight={700} noWrap>
                        {stage.title}
                      </Typography>
                      <Typography variant='caption' color='text.secondary' noWrap>
                        {stage.subtitle}
                      </Typography>
                    </Box>
                  </Stack>

                  <Stack direction='row' spacing={0.5} alignItems='center'>
                    <Chip size='small' color={chipColor} label={statusLabel(stage.status)} />
                    <Tooltip title={expanded ? '收起详情' : '展开详情'}>
                      <IconButton
                        size='small'
                        aria-label={expanded ? '收起详情' : '展开详情'}
                        onClick={() => setExpandedId((prev) => (prev === stage.id ? null : stage.id))}
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
                      {formatProgressLabel(stage.status)}
                    </Typography>
                  </Stack>
                  <LinearProgress
                    variant='determinate'
                    value={Math.max(0, Math.min(100, stage.percent))}
                    color={chipColor === 'default' ? 'primary' : chipColor}
                    sx={{ height: 4, borderRadius: 999 }}
                  />
                </Stack>

                {stage.metrics.length > 0 && (
                  <Stack direction='row' spacing={0.5} useFlexGap flexWrap='wrap'>
                    {stage.metrics.map((item) => (
                      <Chip
                        key={`${stage.id}-${item.label}`}
                        size='small'
                        variant='outlined'
                        color={item.tone ?? 'default'}
                        label={`${item.label}: ${item.value}`}
                      />
                    ))}
                  </Stack>
                )}

                <Collapse in={expanded}>
                  <Stack spacing={1} sx={{ pt: 0.5 }}>
                    {stage.latestStep && (
                      <Typography variant='caption' color='text.secondary'>
                        步骤：{stage.latestStep.label}（{stage.latestStep.status}）
                      </Typography>
                    )}
                    {stage.latestNodeEvent && (
                      <Typography variant='caption' color='text.secondary'>
                        节点：{stage.latestNodeEvent.node_name} · 阶段 {stage.latestNodeEvent.phase}
                        {typeof stage.latestNodeEvent.attempt === 'number'
                          ? ` · 第 ${stage.latestNodeEvent.attempt} 次`
                          : ''}
                      </Typography>
                    )}
                    {stage.latestNodeEvent?.error_summary && (
                      <Typography variant='caption' color='error.main'>
                        {stage.latestNodeEvent.error_summary}
                      </Typography>
                    )}
                    {stage.latestStep?.message && (
                      <Typography variant='caption' color='text.secondary'>
                        {stage.latestStep.message}
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
    </Paper>
  );
}

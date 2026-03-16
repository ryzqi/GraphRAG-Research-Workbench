import type { ElementType } from 'react';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import BlockIcon from '@mui/icons-material/Block';
import FactCheckIcon from '@mui/icons-material/FactCheck';
import GavelIcon from '@mui/icons-material/Gavel';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import HubIcon from '@mui/icons-material/Hub';
import LensIcon from '@mui/icons-material/Lens';
import MergeTypeIcon from '@mui/icons-material/MergeType';
import QueryStatsIcon from '@mui/icons-material/QueryStats';
import RateReviewIcon from '@mui/icons-material/RateReview';
import RuleIcon from '@mui/icons-material/Rule';
import SearchIcon from '@mui/icons-material/Search';
import TaskAltIcon from '@mui/icons-material/TaskAlt';
import TextSnippetIcon from '@mui/icons-material/TextSnippet';
import TuneIcon from '@mui/icons-material/Tune';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import type { KbGraphNode, KbGraphSchema } from './chats';

export type KbTraceStageId =
  | 'stage_1_preprocess'
  | 'stage_2_route'
  | 'stage_3_enhance'
  | 'stage_4_retrieve'
  | 'stage_5_gate'
  | 'stage_6_answer'
  | 'stage_7_finalize';

export interface KbTraceStageMeta {
  id: KbTraceStageId;
  title: string;
  subtitle: string;
  order: number;
}

export interface KbNodeCatalogEntry {
  label: string;
  stageId: KbTraceStageId;
  order: number;
  icon: ElementType;
  color: string;
  phase?: string | null;
}

export const KB_TRACE_STAGE_META: KbTraceStageMeta[] = [
  { id: 'stage_1_preprocess', title: '阶段1 理解问题', subtitle: '整理上下文，确认用户真正想问什么', order: 1 },
  { id: 'stage_2_route', title: '阶段2 选择路径', subtitle: '判断问题复杂度并决定后续路线', order: 2 },
  { id: 'stage_3_enhance', title: '阶段3 补强查询', subtitle: '分解问题并准备检索查询', order: 3 },
  { id: 'stage_4_retrieve', title: '阶段4 检索资料', subtitle: '从知识库取回可用内容', order: 4 },
  { id: 'stage_5_gate', title: '阶段5 核验证据', subtitle: '检查证据是否足够且没有明显冲突', order: 5 },
  { id: 'stage_6_answer', title: '阶段6 组织答案', subtitle: '生成、审查并修复答案', order: 6 },
  { id: 'stage_7_finalize', title: '阶段7 输出结果', subtitle: '整理最终结论并给出结果', order: 7 },
];

const C = {
  preprocess: '#0EA5E9',
  route: '#2563EB',
  enhance: '#0D9488',
  retrieve: '#CA8A04',
  gate: '#EA580C',
  answer: '#9333EA',
  finalize: '#0891B2',
  exit: '#475569',
} as const;

export const KB_NODE_CATALOG: Record<string, KbNodeCatalogEntry> = {
  preprocess_subgraph: { label: '预处理子图', stageId: 'stage_1_preprocess', order: 0, icon: AccountTreeIcon, color: C.preprocess, phase: 'preprocess' },
  merge_context: { label: '上下文合并', stageId: 'stage_1_preprocess', order: 1, icon: MergeTypeIcon, color: C.preprocess, phase: 'preprocess' },
  coref_rewrite: { label: '指代消解', stageId: 'stage_1_preprocess', order: 2, icon: AccountTreeIcon, color: C.preprocess, phase: 'preprocess' },
  ambiguity_check: { label: '歧义判断', stageId: 'stage_1_preprocess', order: 3, icon: HelpOutlineIcon, color: '#7C3AED', phase: 'preprocess' },
  normalize_rewrite: { label: '问题规范', stageId: 'stage_1_preprocess', order: 4, icon: TuneIcon, color: '#4F46E5', phase: 'preprocess' },
  complexity_classify: { label: '复杂度分类', stageId: 'stage_2_route', order: 5, icon: FactCheckIcon, color: C.route, phase: 'route' },
  generate_variants_mod: { label: '中等变体生成', stageId: 'stage_3_enhance', order: 6, icon: HubIcon, color: C.enhance, phase: 'enhance' },
  decomposition: { label: '问题分解', stageId: 'stage_3_enhance', order: 7, icon: HubIcon, color: C.enhance, phase: 'enhance' },
  generate_variants: { label: '多路扩展', stageId: 'stage_3_enhance', order: 8, icon: HubIcon, color: C.enhance, phase: 'enhance' },
  entity_expand: { label: '实体扩展', stageId: 'stage_3_enhance', order: 9, icon: HubIcon, color: '#059669', phase: 'enhance' },
  hyde: { label: 'HyDE扩展', stageId: 'stage_3_enhance', order: 10, icon: AutoFixHighIcon, color: '#16A34A', phase: 'enhance' },
  prepare_messages: { label: '消息整理', stageId: 'stage_3_enhance', order: 11, icon: TextSnippetIcon, color: '#65A30D', phase: 'enhance' },
  preprocess_exit: { label: '预处理出口', stageId: 'stage_3_enhance', order: 12, icon: TaskAltIcon, color: C.enhance, phase: 'enhance' },
  retrieval_subgraph: { label: '检索子图', stageId: 'stage_4_retrieve', order: 13, icon: AccountTreeIcon, color: C.retrieve, phase: 'retrieve' },
  retrieval_budget_plan: { label: '检索预算规划', stageId: 'stage_4_retrieve', order: 14, icon: QueryStatsIcon, color: C.retrieve, phase: 'retrieve' },
  dispatch_subqueries: { label: '子查询派发', stageId: 'stage_4_retrieve', order: 15, icon: HubIcon, color: C.retrieve, phase: 'retrieve' },
  retrieve_subquery: { label: '子查询检索', stageId: 'stage_4_retrieve', order: 16, icon: SearchIcon, color: C.retrieve, phase: 'retrieve' },
  merge_subquery_context: { label: '子查询上下文合并', stageId: 'stage_4_retrieve', order: 17, icon: MergeTypeIcon, color: C.retrieve, phase: 'retrieve' },
  retrieve: { label: '知识检索', stageId: 'stage_4_retrieve', order: 18, icon: SearchIcon, color: C.retrieve, phase: 'retrieve' },
  context_compress: { label: '上下文压缩', stageId: 'stage_4_retrieve', order: 19, icon: TuneIcon, color: C.retrieve, phase: 'retrieve' },
  evidence_gate_subgraph: { label: '证据门控子图', stageId: 'stage_5_gate', order: 20, icon: AccountTreeIcon, color: C.gate, phase: 'judge' },
  doc_gate_dispatch: { label: '文档门控分发', stageId: 'stage_5_gate', order: 21, icon: RuleIcon, color: C.gate, phase: 'judge' },
  doc_gate_sufficiency: { label: '证据充分度', stageId: 'stage_5_gate', order: 22, icon: GavelIcon, color: C.gate, phase: 'judge' },
  doc_gate_answerability: { label: '可回答性', stageId: 'stage_5_gate', order: 23, icon: HelpOutlineIcon, color: C.gate, phase: 'judge' },
  doc_gate_conflict: { label: '证据冲突检测', stageId: 'stage_5_gate', order: 24, icon: WarningAmberIcon, color: C.gate, phase: 'judge' },
  doc_gate_fuse: { label: '证据门控融合', stageId: 'stage_5_gate', order: 25, icon: MergeTypeIcon, color: C.gate, phase: 'judge' },
  doc_gate_route: { label: '文档判定', stageId: 'stage_5_gate', order: 26, icon: TaskAltIcon, color: C.gate, phase: 'judge' },
  transform_query: { label: '查询改写', stageId: 'stage_4_retrieve', order: 27, icon: TuneIcon, color: '#DC2626', phase: 'retrieve' },
  answer_subgraph: { label: '答案子图', stageId: 'stage_6_answer', order: 28, icon: AccountTreeIcon, color: C.answer, phase: 'generate' },
  draft_generate: { label: '草稿生成', stageId: 'stage_6_answer', order: 29, icon: AutoAwesomeIcon, color: C.answer, phase: 'generate' },
  answer_review_dispatch: { label: '审查分发', stageId: 'stage_6_answer', order: 30, icon: RateReviewIcon, color: C.answer, phase: 'verify' },
  answer_review_citation: { label: '引用覆盖审查', stageId: 'stage_6_answer', order: 31, icon: RateReviewIcon, color: C.answer, phase: 'verify' },
  answer_review_factual: { label: '事实正确性审查', stageId: 'stage_6_answer', order: 32, icon: RateReviewIcon, color: C.answer, phase: 'verify' },
  answer_review_answerability: { label: '可回答性审查', stageId: 'stage_6_answer', order: 33, icon: RateReviewIcon, color: C.answer, phase: 'verify' },
  answer_review_fuse: { label: '审查结果融合', stageId: 'stage_6_answer', order: 34, icon: RateReviewIcon, color: C.answer, phase: 'verify' },
  cove_check: { label: '高风险验证判定', stageId: 'stage_6_answer', order: 35, icon: FactCheckIcon, color: C.answer, phase: 'verify' },
  chain_of_verification: { label: '验证链', stageId: 'stage_6_answer', order: 36, icon: FactCheckIcon, color: C.answer, phase: 'verify' },
  claim_citation_check: { label: '断言引用校验', stageId: 'stage_6_answer', order: 37, icon: FactCheckIcon, color: C.answer, phase: 'verify' },
  answer_repair: { label: '答案修复', stageId: 'stage_6_answer', order: 38, icon: AutoFixHighIcon, color: C.answer, phase: 'verify' },
  answer_commit: { label: '答案提交', stageId: 'stage_6_answer', order: 39, icon: TaskAltIcon, color: C.answer, phase: 'generate' },
  force_exit: { label: '提前终止', stageId: 'stage_7_finalize', order: 40, icon: BlockIcon, color: C.exit, phase: 'finalize' },
  confidence_calibrate: { label: '置信度校准', stageId: 'stage_7_finalize', order: 41, icon: FactCheckIcon, color: C.finalize, phase: 'finalize' },
};

const PHASE_TO_STAGE_ID: Partial<Record<string, KbTraceStageId>> = {
  preprocess: 'stage_1_preprocess',
  route: 'stage_2_route',
  enhance: 'stage_3_enhance',
  retrieve: 'stage_4_retrieve',
  judge: 'stage_5_gate',
  verify: 'stage_6_answer',
  finalize: 'stage_7_finalize',
};

export interface ResolveKbNodeCatalogParams {
  nodeId: string;
  schema?: KbGraphSchema | null;
  phase?: string | null;
}

function asNonEmptyText(value: unknown): string | null {
  return typeof value === 'string' && value.trim().length > 0 ? value.trim() : null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function normalizeResolveParams(
  nodeIdOrParams: string | ResolveKbNodeCatalogParams,
  phase?: string | null,
  schema?: KbGraphSchema | null
): ResolveKbNodeCatalogParams {
  if (typeof nodeIdOrParams === 'string') {
    return { nodeId: nodeIdOrParams, phase: phase ?? null, schema: schema ?? null };
  }
  return {
    nodeId: nodeIdOrParams.nodeId,
    phase: nodeIdOrParams.phase ?? null,
    schema: nodeIdOrParams.schema ?? null,
  };
}

export function resolveKbSchemaNode(
  nodeId: string,
  schema: KbGraphSchema | null | undefined
): KbGraphNode | null {
  if (!Array.isArray(schema?.nodes)) {
    return null;
  }
  return schema.nodes.find((node) => node.id === nodeId) ?? null;
}

function resolveSchemaNodePhase(node: KbGraphNode | null): string | null {
  const metadata = asRecord(node?.metadata);
  return asNonEmptyText(metadata?.phase) ?? asNonEmptyText(node?.phase) ?? null;
}

function resolveSchemaNodeOrder(node: KbGraphNode | null): number | null {
  const metadata = asRecord(node?.metadata);
  if (typeof metadata?.order === 'number') {
    return metadata.order;
  }
  return typeof node?.order === 'number' ? node.order : null;
}

function resolveSchemaNodeLabel(node: KbGraphNode | null): string | null {
  const metadata = asRecord(node?.metadata);
  return asNonEmptyText(metadata?.label) ?? asNonEmptyText(node?.label) ?? null;
}

export function resolveKbNodeCatalogEntry(nodeId: string): KbNodeCatalogEntry | null {
  return KB_NODE_CATALOG[nodeId] ?? null;
}

export function resolveKbNodeStageId(
  nodeIdOrParams: string | ResolveKbNodeCatalogParams,
  phase?: string | null,
  schema?: KbGraphSchema | null
): KbTraceStageId {
  const params = normalizeResolveParams(nodeIdOrParams, phase, schema);
  const schemaNode = resolveKbSchemaNode(params.nodeId, params.schema);
  const resolvedPhase = resolveSchemaNodePhase(schemaNode) ?? params.phase;
  if (resolvedPhase && PHASE_TO_STAGE_ID[resolvedPhase]) {
    return PHASE_TO_STAGE_ID[resolvedPhase] as KbTraceStageId;
  }
  const entry = resolveKbNodeCatalogEntry(params.nodeId);
  if (entry) {
    return entry.stageId;
  }
  if (params.phase && PHASE_TO_STAGE_ID[params.phase]) {
    return PHASE_TO_STAGE_ID[params.phase] as KbTraceStageId;
  }
  return 'stage_4_retrieve';
}

export function resolveKbNodeLabelFromCatalog(nodeId: string): string | null {
  return resolveKbNodeCatalogEntry(nodeId)?.label ?? null;
}

export function resolveKbNodeOrder(
  nodeIdOrParams: string | ResolveKbNodeCatalogParams,
  schema?: KbGraphSchema | null
): number {
  const params = normalizeResolveParams(nodeIdOrParams, null, schema);
  const schemaOrder = resolveSchemaNodeOrder(resolveKbSchemaNode(params.nodeId, params.schema));
  if (typeof schemaOrder === 'number') {
    return schemaOrder;
  }
  return resolveKbNodeCatalogEntry(params.nodeId)?.order ?? Number.MAX_SAFE_INTEGER;
}

export function resolveKbNodeVisualMeta(
  nodeId: string,
  schema?: KbGraphSchema | null
) {
  const entry = resolveKbNodeCatalogEntry(nodeId);
  const schemaNode = resolveKbSchemaNode(nodeId, schema);
  const stageId = resolveKbNodeStageId({ nodeId, schema });
  const order = resolveKbNodeOrder({ nodeId, schema });
  const label = resolveSchemaNodeLabel(schemaNode) ?? entry?.label ?? nodeId;
  return {
    label,
    stageId,
    order,
    icon: entry?.icon ?? LensIcon,
    color: entry?.color ?? '#64748B',
    phase: resolveSchemaNodePhase(schemaNode) ?? entry?.phase ?? null,
  };
}

export const resolveKbNodeTheme = resolveKbNodeVisualMeta;

import type { ElementType } from 'react';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import AltRouteIcon from '@mui/icons-material/AltRoute';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import BlockIcon from '@mui/icons-material/Block';
import FactCheckIcon from '@mui/icons-material/FactCheck';
import GavelIcon from '@mui/icons-material/Gavel';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import HubIcon from '@mui/icons-material/Hub';
import LensIcon from '@mui/icons-material/Lens';
import Looks3Icon from '@mui/icons-material/Looks3';
import LooksOneIcon from '@mui/icons-material/LooksOne';
import LooksTwoIcon from '@mui/icons-material/LooksTwo';
import MergeTypeIcon from '@mui/icons-material/MergeType';
import QueryStatsIcon from '@mui/icons-material/QueryStats';
import RateReviewIcon from '@mui/icons-material/RateReview';
import RuleIcon from '@mui/icons-material/Rule';
import SearchIcon from '@mui/icons-material/Search';
import TaskAltIcon from '@mui/icons-material/TaskAlt';
import TextSnippetIcon from '@mui/icons-material/TextSnippet';
import ToggleOnIcon from '@mui/icons-material/ToggleOn';
import TuneIcon from '@mui/icons-material/Tune';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';

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
  { id: 'stage_1_preprocess', title: '阶段1 预处理', subtitle: '上下文融合与歧义处理', order: 1 },
  { id: 'stage_2_route', title: '阶段2 自适应路由', subtitle: '复杂度判定与路径选择', order: 2 },
  { id: 'stage_3_enhance', title: '阶段3 查询增强', subtitle: '拆解、扩展与消息准备', order: 3 },
  { id: 'stage_4_retrieve', title: '阶段4 检索', subtitle: '预算规划与上下文构建', order: 4 },
  { id: 'stage_5_gate', title: '阶段5 证据评估', subtitle: '并行门控与动作决策', order: 5 },
  { id: 'stage_6_answer', title: '阶段6 生成与验证', subtitle: '草稿生成、审查与回修', order: 6 },
  { id: 'stage_7_finalize', title: '阶段7 收敛输出', subtitle: '终态整理与置信度校准', order: 7 },
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
  AMBIGUITY_CHECK_ENABLED: { label: '歧义检查入口', stageId: 'stage_1_preprocess', order: 3, icon: ToggleOnIcon, color: C.preprocess, phase: 'preprocess' },
  ambiguity_check: { label: '歧义判断', stageId: 'stage_1_preprocess', order: 4, icon: HelpOutlineIcon, color: '#7C3AED', phase: 'preprocess' },
  normalize_rewrite: { label: '问题规范', stageId: 'stage_1_preprocess', order: 5, icon: TuneIcon, color: '#4F46E5', phase: 'preprocess' },
  complexity_classify: { label: '复杂度分类', stageId: 'stage_2_route', order: 6, icon: FactCheckIcon, color: C.route, phase: 'route' },
  adaptive_routing: { label: '自适应路由', stageId: 'stage_2_route', order: 7, icon: AltRouteIcon, color: C.route, phase: 'route' },
  simple_path: { label: '简单路径', stageId: 'stage_2_route', order: 8, icon: LooksOneIcon, color: C.route, phase: 'route' },
  moderate_path: { label: '中等路径', stageId: 'stage_2_route', order: 9, icon: LooksTwoIcon, color: C.route, phase: 'route' },
  complex_path: { label: '复杂路径', stageId: 'stage_2_route', order: 10, icon: Looks3Icon, color: C.route, phase: 'route' },
  ENABLE_MULTI_QUERY_MOD: { label: '中等多路开关', stageId: 'stage_3_enhance', order: 11, icon: ToggleOnIcon, color: C.enhance, phase: 'enhance' },
  generate_variants_mod: { label: '中等变体生成', stageId: 'stage_3_enhance', order: 12, icon: HubIcon, color: C.enhance, phase: 'enhance' },
  ENABLE_DECOMPOSITION: { label: '拆解开关', stageId: 'stage_3_enhance', order: 13, icon: ToggleOnIcon, color: C.enhance, phase: 'enhance' },
  decomposition: { label: '问题分解', stageId: 'stage_3_enhance', order: 14, icon: HubIcon, color: C.enhance, phase: 'enhance' },
  ENABLE_MULTI_QUERY: { label: '多路开关', stageId: 'stage_3_enhance', order: 15, icon: ToggleOnIcon, color: C.enhance, phase: 'enhance' },
  generate_variants: { label: '多路扩展', stageId: 'stage_3_enhance', order: 16, icon: HubIcon, color: C.enhance, phase: 'enhance' },
  entity_expand: { label: '实体扩展', stageId: 'stage_3_enhance', order: 17, icon: HubIcon, color: '#059669', phase: 'enhance' },
  ENABLE_HYDE: { label: 'HyDE开关', stageId: 'stage_3_enhance', order: 18, icon: ToggleOnIcon, color: C.enhance, phase: 'enhance' },
  hyde: { label: 'HyDE扩展', stageId: 'stage_3_enhance', order: 19, icon: AutoFixHighIcon, color: '#16A34A', phase: 'enhance' },
  prepare_messages: { label: '消息整理', stageId: 'stage_3_enhance', order: 20, icon: TextSnippetIcon, color: '#65A30D', phase: 'enhance' },
  preprocess_exit: { label: '预处理出口', stageId: 'stage_3_enhance', order: 21, icon: TaskAltIcon, color: C.enhance, phase: 'enhance' },
  retrieval_subgraph: { label: '检索子图', stageId: 'stage_4_retrieve', order: 22, icon: AccountTreeIcon, color: C.retrieve, phase: 'retrieve' },
  retrieval_budget_plan: { label: '检索预算规划', stageId: 'stage_4_retrieve', order: 23, icon: QueryStatsIcon, color: C.retrieve, phase: 'retrieve' },
  dispatch_subqueries: { label: '子查询派发', stageId: 'stage_4_retrieve', order: 24, icon: HubIcon, color: C.retrieve, phase: 'retrieve' },
  retrieve_subquery: { label: '子查询检索', stageId: 'stage_4_retrieve', order: 25, icon: SearchIcon, color: C.retrieve, phase: 'retrieve' },
  merge_subquery_context: { label: '子查询上下文合并', stageId: 'stage_4_retrieve', order: 26, icon: MergeTypeIcon, color: C.retrieve, phase: 'retrieve' },
  retrieve: { label: '知识检索', stageId: 'stage_4_retrieve', order: 27, icon: SearchIcon, color: C.retrieve, phase: 'retrieve' },
  context_compress: { label: '上下文压缩', stageId: 'stage_4_retrieve', order: 28, icon: TuneIcon, color: C.retrieve, phase: 'retrieve' },
  evidence_gate_subgraph: { label: '证据门控子图', stageId: 'stage_5_gate', order: 29, icon: AccountTreeIcon, color: C.gate, phase: 'judge' },
  doc_gate_dispatch: { label: '文档门控分发', stageId: 'stage_5_gate', order: 30, icon: RuleIcon, color: C.gate, phase: 'judge' },
  doc_gate_sufficiency: { label: '证据充分度', stageId: 'stage_5_gate', order: 31, icon: GavelIcon, color: C.gate, phase: 'judge' },
  doc_gate_answerability: { label: '可回答性', stageId: 'stage_5_gate', order: 32, icon: HelpOutlineIcon, color: C.gate, phase: 'judge' },
  doc_gate_conflict: { label: '证据冲突检测', stageId: 'stage_5_gate', order: 33, icon: WarningAmberIcon, color: C.gate, phase: 'judge' },
  doc_gate_fuse: { label: '证据门控融合', stageId: 'stage_5_gate', order: 34, icon: MergeTypeIcon, color: C.gate, phase: 'judge' },
  doc_gate_route: { label: '文档判定', stageId: 'stage_5_gate', order: 35, icon: TaskAltIcon, color: C.gate, phase: 'judge' },
  transform_query: { label: '查询改写', stageId: 'stage_4_retrieve', order: 36, icon: TuneIcon, color: '#DC2626', phase: 'retrieve' },
  answer_subgraph: { label: '答案子图', stageId: 'stage_6_answer', order: 37, icon: AccountTreeIcon, color: C.answer, phase: 'generate' },
  draft_generate: { label: '草稿生成', stageId: 'stage_6_answer', order: 38, icon: AutoAwesomeIcon, color: C.answer, phase: 'generate' },
  generate: { label: '答案生成', stageId: 'stage_6_answer', order: 38, icon: AutoAwesomeIcon, color: C.answer, phase: 'generate' },
  answer_review_dispatch: { label: '审查分发', stageId: 'stage_6_answer', order: 39, icon: RateReviewIcon, color: C.answer, phase: 'verify' },
  answer_review_citation: { label: '引用覆盖审查', stageId: 'stage_6_answer', order: 40, icon: RateReviewIcon, color: C.answer, phase: 'verify' },
  answer_review_factual: { label: '事实正确性审查', stageId: 'stage_6_answer', order: 41, icon: RateReviewIcon, color: C.answer, phase: 'verify' },
  answer_review_answerability: { label: '可回答性审查', stageId: 'stage_6_answer', order: 42, icon: RateReviewIcon, color: C.answer, phase: 'verify' },
  answer_review_fuse: { label: '审查结果融合', stageId: 'stage_6_answer', order: 43, icon: RateReviewIcon, color: C.answer, phase: 'verify' },
  answer_review: { label: '答案审查', stageId: 'stage_6_answer', order: 43, icon: RateReviewIcon, color: C.answer, phase: 'verify' },
  cove_check: { label: '高风险验证判定', stageId: 'stage_6_answer', order: 44, icon: FactCheckIcon, color: C.answer, phase: 'verify' },
  chain_of_verification: { label: '验证链', stageId: 'stage_6_answer', order: 45, icon: FactCheckIcon, color: C.answer, phase: 'verify' },
  claim_citation_check: { label: '断言引用校验', stageId: 'stage_6_answer', order: 46, icon: FactCheckIcon, color: C.answer, phase: 'verify' },
  answer_repair: { label: '答案修复', stageId: 'stage_6_answer', order: 47, icon: AutoFixHighIcon, color: C.answer, phase: 'verify' },
  answer_commit: { label: '答案提交', stageId: 'stage_6_answer', order: 48, icon: TaskAltIcon, color: C.answer, phase: 'generate' },
  finalize: { label: '答案整理', stageId: 'stage_7_finalize', order: 49, icon: TaskAltIcon, color: C.finalize, phase: 'finalize' },
  force_exit: { label: '提前终止', stageId: 'stage_7_finalize', order: 50, icon: BlockIcon, color: C.exit, phase: 'finalize' },
  confidence_calibrate: { label: '置信度校准', stageId: 'stage_7_finalize', order: 51, icon: FactCheckIcon, color: C.finalize, phase: 'finalize' },
};

const PHASE_TO_STAGE_ID: Partial<Record<string, KbTraceStageId>> = {
  preprocess: 'stage_1_preprocess',
  route: 'stage_2_route',
  enhance: 'stage_3_enhance',
  retrieve: 'stage_4_retrieve',
  judge: 'stage_5_gate',
  generate: 'stage_6_answer',
  verify: 'stage_6_answer',
  finalize: 'stage_7_finalize',
};

export function resolveKbNodeCatalogEntry(nodeId: string): KbNodeCatalogEntry | null {
  return KB_NODE_CATALOG[nodeId] ?? null;
}

export function resolveKbNodeStageId(nodeId: string, phase?: string | null): KbTraceStageId {
  const entry = resolveKbNodeCatalogEntry(nodeId);
  if (entry) {
    return entry.stageId;
  }
  if (phase && PHASE_TO_STAGE_ID[phase]) {
    return PHASE_TO_STAGE_ID[phase] as KbTraceStageId;
  }
  return 'stage_4_retrieve';
}

export function resolveKbNodeLabelFromCatalog(nodeId: string): string | null {
  return resolveKbNodeCatalogEntry(nodeId)?.label ?? null;
}

export function resolveKbNodeOrder(nodeId: string): number {
  return resolveKbNodeCatalogEntry(nodeId)?.order ?? Number.MAX_SAFE_INTEGER;
}

export function resolveKbNodeVisualMeta(nodeId: string) {
  return (
    resolveKbNodeCatalogEntry(nodeId) ?? {
      label: nodeId,
      stageId: 'stage_4_retrieve' as KbTraceStageId,
      order: Number.MAX_SAFE_INTEGER,
      icon: LensIcon,
      color: '#64748B',
      phase: null,
    }
  );
}

export const resolveKbNodeTheme = resolveKbNodeVisualMeta;

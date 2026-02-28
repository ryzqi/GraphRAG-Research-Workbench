import type { ChatNodeDisplayItem, ChatNodeIoEvent } from './chats';

export interface KbChatFlowDetailItem {
  key: string;
  label: string;
  value: string | string[];
}

type DetailSectionKind = 'input' | 'output';

interface NodeDetailPolicy {
  input: string[];
  output: string[];
}

const NODE_DETAIL_POLICY_MAP: Record<string, NodeDetailPolicy> = {
  merge_context: {
    input: ['user_input'],
    output: [
      'current_question',
      'summary_source',
      'compression_ratio',
      'llm_resolve_used',
      'merge_fallback_used',
      'merged_context',
      'memory_included',
    ],
  },
  rewrite_plan: {
    input: ['user_input'],
    output: ['selected_query', 'selected_candidate_id', 'candidate_count', 'strategy', 'fallback_reason'],
  },
  rewrite_dispatch: {
    input: ['selected_query'],
    output: ['mode', 'branch_count', 'selected_queries', 'reason'],
  },
  rewrite_branch_retrieve: {
    input: ['query'],
    output: ['query', 'retrieval_count', 'success', 'reason'],
  },
  rewrite_fuse: {
    input: ['rewrite_branch_runs'],
    output: ['selected_query', 'selected_candidate_id', 'candidate_count', 'fallback_reason'],
  },
  coref_rewrite: {
    input: ['query'],
    output: ['coref_query', 'confidence', 'selected_mention', 'reason', 'needs_clarification_hint', 'rewritten'],
  },
  ambiguity_check: {
    input: ['query'],
    output: ['ambiguous', 'reason_code', 'confidence', 'action', 'final_answer'],
  },
  normalize_rewrite: {
    input: ['query'],
    output: ['normalized_query', 'rewritten'],
  },
  complexity_classify: {
    input: ['normalized_query'],
    output: ['complexity', 'signals', 'confidence'],
  },
  adaptive_routing: {
    input: ['complexity'],
    output: ['route', 'reason', 'strategy'],
  },
  simple_path: {
    input: ['normalized_query'],
    output: ['route', 'reason'],
  },
  moderate_path: {
    input: ['normalized_query'],
    output: ['route', 'reason', 'variants_enabled'],
  },
  complex_path: {
    input: ['normalized_query'],
    output: ['route', 'reason', 'decomposition_enabled', 'hyde_enabled'],
  },
  decomposition: {
    input: ['normalized_query'],
    output: ['sub_queries', 'count'],
  },
  multi_query_check: {
    input: ['normalized_query'],
    output: ['query_count', 'reason'],
  },
  generate_variants: {
    input: ['normalized_query'],
    output: ['multi_queries', 'count'],
  },
  entity_expand: {
    input: ['normalized_query'],
    output: [
      'multi_queries',
      'input_count',
      'expanded_count',
      'added_count',
      'pruned_count',
      'min_confidence',
      'drift_guardrail_triggered',
      'fallback_reason',
    ],
  },
  hyde: {
    input: ['normalized_query'],
    output: ['enabled', 'hyde_doc'],
  },
  hyde_check: {
    input: ['normalized_query'],
    output: ['enabled', 'reason'],
  },
  prepare_messages: {
    input: ['normalized_query', 'query_strategy'],
    output: [
      'query_bundle_items_count',
      'message_plan_candidate_count',
      'message_plan_dropped_count',
      'fallback_reason',
      'quality_signals',
      'query_items',
    ],
  },
  dispatch_subqueries: {
    input: ['query_strategy', 'query_items'],
    output: ['mode', 'branch_count', 'reason'],
  },
  retrieval_budget_plan: {
    input: ['complexity', 'failure_reasons'],
    output: ['per_query_top_k', 'global_candidates_limit', 'rerank_input_limit'],
  },
  retrieve_subquery: {
    input: ['query', 'kind'],
    output: ['query', 'kind', 'success'],
  },
  merge_subquery_context: {
    input: ['subquery_runs_count'],
    output: ['mode', 'branch_count', 'evidence_count'],
  },
  retrieve: {
    input: ['query_items', 'normalized_query'],
    output: ['evidence_count', 'attempted'],
  },
  context_compress: {
    input: ['final_context'],
    output: ['token_limit', 'input_tokens', 'output_tokens', 'truncated'],
  },
  doc_gate_precheck: {
    input: ['question'],
    output: ['passed', 'reason', 'threshold', 'evidence_score'],
  },
  doc_grader_llm: {
    input: ['question'],
    output: ['skipped', 'passed', 'reason', 'confidence', 'fallback_reason'],
  },
  doc_gate_route: {
    input: ['question'],
    output: ['passed', 'decision_source', 'confidence', 'evidence_score', 'risk_level', 'action'],
  },
  doc_gate_sufficiency: {
    input: ['final_context'],
    output: ['passed', 'confidence', 'reason'],
  },
  doc_gate_answerability: {
    input: ['final_context'],
    output: ['passed', 'confidence', 'reason'],
  },
  doc_gate_conflict: {
    input: ['final_context'],
    output: ['passed', 'confidence', 'reason'],
  },
  doc_gate_fuse: {
    input: ['gate_scores'],
    output: ['action', 'reason', 'confidence'],
  },
  transform_query: {
    input: ['normalized_query'],
    output: ['normalized_query', 'rewritten'],
  },
  answer_subgraph: {
    input: ['question'],
    output: ['next_step', 'reason', 'degrade_reason', 'best_answer', 'repair_attempts'],
  },
  draft_generate: {
    input: ['question'],
    output: ['draft_answer', 'final_answer'],
  },
  answer_self_check: {
    input: ['question'],
    output: ['passed', 'reason', 'fallback_reason'],
  },
  answer_repair: {
    input: ['draft_answer'],
    output: ['repair_attempt', 'fallback_reason', 'final_answer'],
  },
  answer_commit: {
    input: ['reason'],
    output: ['next_step', 'reason', 'degrade_reason', 'best_answer'],
  },
  generate: {
    input: ['question'],
    output: ['draft_answer', 'final_answer'],
  },
  answer_review: {
    input: ['question'],
    output: ['passed', 'best_answer', 'action'],
  },
  answer_review_dispatch: {
    input: ['draft_answer'],
    output: ['branch_count', 'dispatch_reason'],
  },
  answer_review_citation: {
    input: ['draft_answer'],
    output: ['passed', 'reason', 'coverage_ratio'],
  },
  answer_review_factual: {
    input: ['draft_answer'],
    output: ['passed', 'reason', 'factual_risk'],
  },
  answer_review_answerability: {
    input: ['draft_answer'],
    output: ['passed', 'reason'],
  },
  answer_review_fuse: {
    input: ['review_breakdown'],
    output: ['passed', 'action', 'reason', 'review_confidence'],
  },
  cove_check: {
    input: ['query_risk_level'],
    output: ['enabled', 'reason', 'risk_level'],
  },
  chain_of_verification: {
    input: ['draft_answer'],
    output: ['verification_rounds', 'failed_claims', 'repair_action'],
  },
  claim_citation_check: {
    input: ['draft_answer'],
    output: ['passed', 'missing_claims', 'invalid_citations'],
  },
  confidence_calibrate: {
    input: ['final_answer'],
    output: ['confidence_score', 'confidence_level', 'signals', 'reason'],
  },
  finalize: {
    input: ['draft_answer'],
    output: ['final_answer'],
  },
  force_exit: {
    input: ['action', 'reason'],
    output: ['final_answer', 'reason'],
  },
};

function detailItemText(value: string | string[]): string {
  return Array.isArray(value) ? value.join('\n') : value;
}

function normalizeDetailItems(
  items: ChatNodeDisplayItem[] | KbChatFlowDetailItem[] | null | undefined
): KbChatFlowDetailItem[] {
  if (!items || items.length === 0) {
    return [];
  }
  return items.map((item) => ({
    key: item.key,
    label: item.label,
    value: item.value,
  }));
}

function asText(value: string | string[]): string {
  return Array.isArray(value) ? value.join('\n') : value;
}

function inferRiskHint(
  section: DetailSectionKind,
  items: KbChatFlowDetailItem[]
): string | null {
  if (section !== 'output') {
    return null;
  }
  const byKey = new Map(items.map((item) => [item.key, asText(item.value)]));
  const confidenceLevel = (byKey.get('confidence_level') ?? '').toLowerCase();
  const riskLevel = (byKey.get('risk_level') ?? byKey.get('review_risk_level') ?? '').toLowerCase();
  const action = (byKey.get('action') ?? '').toLowerCase();
  const confidenceScoreRaw = byKey.get('confidence_score');
  const confidenceScore = confidenceScoreRaw ? Number.parseFloat(confidenceScoreRaw) : Number.NaN;

  if (confidenceLevel === 'low' || (!Number.isNaN(confidenceScore) && confidenceScore < 0.5)) {
    return '当前结论置信度较低，建议补充约束或交叉验证来源。';
  }
  if (riskLevel.includes('high') || riskLevel.includes('冲突')) {
    return '检测到高风险或证据冲突，请优先核对关键引用。';
  }
  if (action.includes('retry') || action.includes('重试')) {
    return '该节点建议重试路径，关注改写后的查询与证据覆盖。';
  }
  return null;
}

export function selectKbChatFlowDetailItems(params: {
  nodeId: string;
  section: DetailSectionKind;
  items: ChatNodeDisplayItem[] | KbChatFlowDetailItem[] | null | undefined;
  event: ChatNodeIoEvent | null;
}): KbChatFlowDetailItem[] {
  const normalized = normalizeDetailItems(params.items);
  if (params.event?.error_summary && !normalized.some((item) => item.key === 'error_summary')) {
    normalized.push({ key: 'error_summary', label: '错误信息', value: params.event.error_summary });
  }

  const errorItems = normalized.filter((item) => item.key === 'error_summary');
  const candidates = normalized.filter((item) => item.key !== 'error_summary');
  const selected: KbChatFlowDetailItem[] = [];
  const seen = new Set<string>();
  const limit = Number.MAX_SAFE_INTEGER;
  const policyKeys = [...(NODE_DETAIL_POLICY_MAP[params.nodeId]?.[params.section] ?? [])];

  if (params.nodeId === 'ambiguity_check' && params.section === 'output') {
    const action = candidates.find((item) => item.key === 'action');
    const actionText = action ? detailItemText(action.value).toLowerCase() : '';
    if (actionText.includes('clarify') || actionText.includes('澄清')) {
      policyKeys.splice(0, policyKeys.length, 'action', 'final_answer');
    }
  }

  const appendItem = (item: KbChatFlowDetailItem | undefined) => {
    if (!item) {
      return;
    }
    const identity = `${item.key}:${detailItemText(item.value)}`;
    if (seen.has(identity)) {
      return;
    }
    selected.push(item);
    seen.add(identity);
  };

  for (const key of policyKeys) {
    appendItem(candidates.find((item) => item.key === key));
    if (selected.length >= limit) {
      break;
    }
  }

  if (selected.length < limit) {
    for (const item of candidates) {
      appendItem(item);
      if (selected.length >= limit) {
        break;
      }
    }
  }

  const result = [...selected, ...errorItems];
  const riskHint = inferRiskHint(params.section, result);
  if (riskHint) {
    result.push({ key: 'risk_hint', label: '风险提示', value: riskHint });
  }
  return result;
}

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
  preprocess_subgraph: {
    input: ['user_input'],
    output: ['normalized_query', 'final_answer'],
  },
  merge_context: {
    input: ['user_input'],
    output: ['merged_context'],
  },
  coref_rewrite: {
    input: ['query'],
    output: ['coref_query'],
  },
  ambiguity_check: {
    input: ['query'],
    output: ['action', 'final_answer'],
  },
  normalize_rewrite: {
    input: ['query'],
    output: ['normalized_query'],
  },
  complexity_classify: {
    input: ['normalized_query'],
    output: ['complexity_level'],
  },
  generate_variants_mod: {
    input: ['normalized_query'],
    output: ['multi_queries'],
  },
  decomposition: {
    input: ['normalized_query'],
    output: ['sub_queries'],
  },
  generate_variants: {
    input: ['normalized_query'],
    output: ['multi_queries'],
  },
  entity_expand: {
    input: ['normalized_query'],
    output: ['multi_queries'],
  },
  hyde: {
    input: ['normalized_query'],
    output: ['hyde_doc'],
  },
  prepare_messages: {
    input: ['normalized_query', 'query_strategy'],
    output: ['query_items'],
  },
  preprocess_exit: {
    input: ['normalized_query'],
    output: ['normalized_query', 'final_answer'],
  },
  retrieval_subgraph: {
    input: ['query_items', 'normalized_query'],
    output: ['evidence_count'],
  },
  dispatch_subqueries: {
    input: ['query_strategy', 'query_items'],
    output: ['mode'],
  },
  retrieval_budget_plan: {
    input: ['complexity_level', 'query_items', 'reason'],
    output: [],
  },
  retrieve_subquery: {
    input: ['query', 'kind'],
    output: ['success'],
  },
  merge_subquery_context: {
    input: ['subquery_runs_count'],
    output: ['evidence_count'],
  },
  retrieve: {
    input: ['query_items', 'normalized_query'],
    output: ['evidence_count'],
  },
  context_compress: {
    input: ['final_context'],
    output: ['truncated'],
  },
  evidence_gate_subgraph: {
    input: ['question', 'final_context'],
    output: ['passed', 'action', 'reason'],
  },
  doc_gate_dispatch: {
    input: ['question', 'final_context'],
    output: ['action'],
  },
  doc_gate_route: {
    input: ['question'],
    output: ['passed', 'action'],
  },
  doc_gate_sufficiency: {
    input: ['final_context'],
    output: ['passed', 'reason'],
  },
  doc_gate_answerability: {
    input: ['final_context'],
    output: ['passed', 'reason'],
  },
  doc_gate_conflict: {
    input: ['final_context'],
    output: ['passed', 'reason'],
  },
  doc_gate_fuse: {
    input: ['gate_scores'],
    output: ['action', 'reason'],
  },
  transform_query: {
    input: ['normalized_query'],
    output: ['normalized_query'],
  },
  answer_subgraph: {
    input: ['question'],
    output: ['best_answer'],
  },
  draft_generate: {
    input: ['question'],
    output: ['draft_answer', 'final_answer'],
  },
  answer_repair: {
    input: ['draft_answer'],
    output: ['final_answer'],
  },
  answer_commit: {
    input: ['reason'],
    output: ['best_answer'],
  },
  answer_review_dispatch: {
    input: ['draft_answer'],
    output: ['checks'],
  },
  answer_review_citation: {
    input: ['draft_answer'],
    output: ['passed', 'reason'],
  },
  answer_review_factual: {
    input: ['draft_answer'],
    output: ['passed', 'reason'],
  },
  answer_review_answerability: {
    input: ['draft_answer'],
    output: ['passed', 'reason'],
  },
  answer_review_fuse: {
    input: ['review_breakdown'],
    output: ['passed', 'reason', 'action'],
  },
  cove_check: {
    input: ['draft_answer'],
    output: ['action', 'reason'],
  },
  chain_of_verification: {
    input: ['draft_answer'],
    output: ['passed', 'reason', 'repair_action'],
  },
  claim_citation_check: {
    input: ['draft_answer'],
    output: ['passed'],
  },
  confidence_calibrate: {
    input: ['final_answer'],
    output: ['confidence_level', 'reason'],
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
  const hasPolicy = Object.prototype.hasOwnProperty.call(NODE_DETAIL_POLICY_MAP, params.nodeId);
  const policyKeys = [...(NODE_DETAIL_POLICY_MAP[params.nodeId]?.[params.section] ?? [])];
  const shouldAppendUncuratedItems = params.section === 'input' || !hasPolicy;

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

  if (shouldAppendUncuratedItems && selected.length < limit) {
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

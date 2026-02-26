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

const DETAIL_ITEM_LIMIT: Record<DetailSectionKind, number> = {
  input: 2,
  output: 2,
};

const NODE_DETAIL_LIMIT_OVERRIDES: Partial<
  Record<string, Partial<Record<DetailSectionKind, number>>>
> = {
  coref_rewrite: { output: 4 },
  prepare_messages: { output: 4 },
};

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
  doc_grader: {
    input: ['question'],
    output: ['passed', 'action'],
  },
  transform_query: {
    input: ['normalized_query'],
    output: ['normalized_query', 'rewritten'],
  },
  generate: {
    input: ['question'],
    output: ['draft_answer', 'final_answer'],
  },
  answer_review: {
    input: ['question'],
    output: ['passed', 'best_answer', 'action'],
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
  const limit =
    NODE_DETAIL_LIMIT_OVERRIDES[params.nodeId]?.[params.section] ??
    DETAIL_ITEM_LIMIT[params.section];
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

  return [...selected, ...errorItems];
}

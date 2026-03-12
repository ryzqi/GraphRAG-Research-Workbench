import { describe, expect, it } from 'vitest';

import { KB_TRACE_STAGE_META, resolveKbNodeVisualMeta } from './kbNodeCatalog';

const CURRENT_KB_CHAT_NODE_IDS = [
  'preprocess_subgraph',
  'merge_context',
  'coref_rewrite',
  'AMBIGUITY_CHECK_ENABLED',
  'ambiguity_check',
  'normalize_rewrite',
  'complexity_classify',
  'adaptive_routing',
  'simple_path',
  'moderate_path',
  'complex_path',
  'ENABLE_MULTI_QUERY_MOD',
  'generate_variants_mod',
  'ENABLE_DECOMPOSITION',
  'decomposition',
  'ENABLE_MULTI_QUERY',
  'generate_variants',
  'entity_expand',
  'ENABLE_HYDE',
  'hyde',
  'prepare_messages',
  'preprocess_exit',
  'retrieval_subgraph',
  'retrieval_budget_plan',
  'dispatch_subqueries',
  'retrieve_subquery',
  'merge_subquery_context',
  'retrieve',
  'context_compress',
  'evidence_gate_subgraph',
  'doc_gate_dispatch',
  'doc_gate_sufficiency',
  'doc_gate_answerability',
  'doc_gate_conflict',
  'doc_gate_fuse',
  'doc_gate_route',
  'transform_query',
  'answer_subgraph',
  'draft_generate',
  'generate',
  'answer_review_dispatch',
  'answer_review_citation',
  'answer_review_factual',
  'answer_review_answerability',
  'answer_review_fuse',
  'answer_review',
  'cove_check',
  'chain_of_verification',
  'claim_citation_check',
  'answer_repair',
  'answer_commit',
  'finalize',
  'force_exit',
  'confidence_calibrate',
] as const;

describe('kbNodeCatalog', () => {
  it('defines label, stage and icon metadata for every current KB Chat node', () => {
    const stageIds = new Set(KB_TRACE_STAGE_META.map((stage) => stage.id));

    CURRENT_KB_CHAT_NODE_IDS.forEach((nodeId) => {
      const meta = resolveKbNodeVisualMeta(nodeId);
      expect(meta.label).not.toBe(nodeId);
      expect(stageIds.has(meta.stageId)).toBe(true);
      expect(meta.icon).toBeTruthy();
      expect(meta.color).toMatch(/^#/);
    });
  });
});

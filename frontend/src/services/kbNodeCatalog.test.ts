import { describe, expect, it } from 'vitest';

import {
  KB_TRACE_STAGE_META,
  resolveKbNodeCatalogEntry,
  resolveKbNodeOrder,
  resolveKbNodeStageId,
  resolveKbNodeVisualMeta,
} from './kbNodeCatalog';

const CURRENT_KB_CHAT_NODE_IDS = [
  'preprocess_subgraph',
  'merge_context',
  'coref_rewrite',
  'ambiguity_check',
  'normalize_rewrite',
  'complexity_classify',
  'generate_variants_mod',
  'decomposition',
  'generate_variants',
  'entity_expand',
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
  'doc_gate_sufficiency',
  'doc_gate_route',
  'transform_query',
  'answer_subgraph',
  'draft_generate',
  'answer_review_dispatch',
  'answer_review_citation',
  'answer_review_factual',
  'answer_review_answerability',
  'answer_review_fuse',
  'answer_repair',
  'answer_commit',
  'force_exit',
  'confidence_calibrate',
] as const;

const EXPECTED_NODE_ORDERS: Record<(typeof CURRENT_KB_CHAT_NODE_IDS)[number], number> = {
  preprocess_subgraph: 0,
  merge_context: 1,
  coref_rewrite: 2,
  ambiguity_check: 3,
  normalize_rewrite: 4,
  complexity_classify: 5,
  generate_variants_mod: 6,
  decomposition: 7,
  generate_variants: 8,
  entity_expand: 9,
  hyde: 10,
  prepare_messages: 11,
  preprocess_exit: 12,
  retrieval_subgraph: 13,
  retrieval_budget_plan: 14,
  dispatch_subqueries: 15,
  retrieve_subquery: 16,
  merge_subquery_context: 17,
  retrieve: 18,
  context_compress: 19,
  evidence_gate_subgraph: 20,
  doc_gate_sufficiency: 21,
  doc_gate_route: 22,
  transform_query: 23,
  answer_subgraph: 24,
  draft_generate: 25,
  answer_review_dispatch: 26,
  answer_review_citation: 27,
  answer_review_factual: 28,
  answer_review_answerability: 29,
  answer_review_fuse: 30,
  answer_repair: 31,
  answer_commit: 32,
  force_exit: 33,
  confidence_calibrate: 34,
};

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

  it('prefers graph schema metadata for stage and order before local catalog fallback', () => {
    const schema = {
      version: '1.1',
      hash: 'schema-hash',
      nodes: [
        {
          id: 'merge_context',
          label: '旧标签',
          phase: 'preprocess',
          order: 1,
          metadata: {
            label: '上下文整合',
            phase: 'finalize',
            order: 99,
          },
        },
      ],
      edges: [],
    };

    expect(resolveKbNodeStageId({ nodeId: 'merge_context', schema })).toBe('stage_7_finalize');
    expect(resolveKbNodeOrder({ nodeId: 'merge_context', schema })).toBe(99);
  });

  it('keeps remaining fallback catalog node order aligned with backend metadata', () => {
    CURRENT_KB_CHAT_NODE_IDS.forEach((nodeId) => {
      expect(resolveKbNodeOrder(nodeId)).toBe(EXPECTED_NODE_ORDERS[nodeId]);
    });
  });

  it('does not keep deprecated preprocess shell nodes in local catalog fallback', () => {
    [
      'AMBIGUITY_CHECK_ENABLED',
      'adaptive_routing',
      'simple_path',
      'moderate_path',
      'complex_path',
      'ENABLE_MULTI_QUERY_MOD',
      'ENABLE_DECOMPOSITION',
      'ENABLE_MULTI_QUERY',
      'ENABLE_HYDE',
    ].forEach((nodeId) => {
      expect(resolveKbNodeCatalogEntry(nodeId)).toBeNull();
    });
  });

  it('does not keep deprecated answer aliases in local catalog fallback', () => {
    ['generate', 'answer_review', 'finalize'].forEach((nodeId) => {
      expect(resolveKbNodeCatalogEntry(nodeId)).toBeNull();
    });
  });

  it('does not keep pruned live gate and verification nodes in local catalog fallback', () => {
    [
      'doc_gate_dispatch',
      'doc_gate_answerability',
      'doc_gate_conflict',
      'doc_gate_fuse',
      'cove_check',
      'chain_of_verification',
      'claim_citation_check',
    ].forEach((nodeId) => {
      expect(resolveKbNodeCatalogEntry(nodeId)).toBeNull();
    });
  });
});

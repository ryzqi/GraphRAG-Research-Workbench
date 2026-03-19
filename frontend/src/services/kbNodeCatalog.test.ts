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
  'resolve_reference',
  'ambiguity_check',
  'query_normalize',
  'query_plan',
  'decomposition',
  'generate_variants',
  'entity_expand',
  'hyde',
  'query_plan_finalize',
  'preprocess_exit',
  'retrieval_subgraph',
  'retrieval_plan',
  'dispatch_subqueries',
  'retrieve_subquery',
  'merge_subquery_context',
  'retrieve',
  'context_compress',
  'transform_query',
  'answer_subgraph',
  'draft_generate',
  'answer_review_dispatch',
  'answer_review_citation',
  'answer_review',
  'answer_review_fuse',
  'answer_repair',
  'answer_commit',
  'force_exit',
] as const;

const EXPECTED_NODE_ORDERS: Record<(typeof CURRENT_KB_CHAT_NODE_IDS)[number], number> = {
  preprocess_subgraph: 0,
  merge_context: 1,
  resolve_reference: 2,
  ambiguity_check: 3,
  query_normalize: 4,
  query_plan: 5,
  decomposition: 6,
  generate_variants: 7,
  entity_expand: 8,
  hyde: 9,
  query_plan_finalize: 10,
  preprocess_exit: 11,
  retrieval_subgraph: 12,
  retrieval_plan: 13,
  dispatch_subqueries: 14,
  retrieve_subquery: 15,
  merge_subquery_context: 16,
  retrieve: 17,
  context_compress: 18,
  transform_query: 19,
  answer_subgraph: 20,
  draft_generate: 21,
  answer_review_dispatch: 22,
  answer_review_citation: 23,
  answer_review: 24,
  answer_review_fuse: 25,
  answer_repair: 26,
  answer_commit: 27,
  force_exit: 28,
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

  it('does not keep deprecated answer shell aliases in local catalog fallback', () => {
    ['generate', 'finalize'].forEach((nodeId) => {
      expect(resolveKbNodeCatalogEntry(nodeId)).toBeNull();
    });
  });

  it('keeps the live merged answer review node in local catalog fallback', () => {
    expect(resolveKbNodeCatalogEntry('answer_review')?.label).toBe('回答有效性审查');
  });

  it('does not keep pruned live gate and verification nodes in local catalog fallback', () => {
    [
      'evidence_gate_subgraph',
      'doc_gate_sufficiency',
      'doc_gate_route',
      'doc_gate_dispatch',
      'doc_gate_answerability',
      'doc_gate_conflict',
      'doc_gate_fuse',
      'cove_check',
      'chain_of_verification',
      'claim_citation_check',
      'confidence_calibrate',
    ].forEach((nodeId) => {
      expect(resolveKbNodeCatalogEntry(nodeId)).toBeNull();
    });
  });

  it('keeps live Scheme B preprocess enhancement nodes and drops retired aliases', () => {
    [
      ['decomposition', '问题拆解'],
      ['generate_variants', '多路查询扩展'],
      ['entity_expand', '实体扩展'],
      ['hyde', '假设文档扩展'],
      ['query_plan_finalize', '查询定稿'],
    ].forEach(([nodeId, label]) => {
      expect(resolveKbNodeCatalogEntry(nodeId)?.label).toBe(label);
    });

    ['complexity_classify', 'generate_variants_mod', 'prepare_messages'].forEach((nodeId) => {
      expect(resolveKbNodeCatalogEntry(nodeId)).toBeNull();
    });
  });
});

import { describe, expect, it } from 'vitest';

import type { KbChatConfig } from './chats';
import { toKbGraphSchemaQuery } from './chats';

const removedConfigKeys = [
  'query_rewrite_enabled',
  'ambiguity_check_enabled',
  'normalize_llm_enabled',
  'normalize_alias_max',
  'hyde_enabled',
  'entity_expand_enabled',
  'entity_expand_timeout_seconds',
  'entity_expand_max_candidates',
  'entity_expand_max_variants',
  'entity_expand_min_confidence',
  'parallel_retrieval_enabled',
  'doc_gate_rule_threshold',
  'doc_gate_llm_confidence_floor',
  'doc_gate_fallback_open_when_evidence_ok',
  'doc_gate_cache_ttl_seconds',
  'hybrid_retrieval_enabled',
  'rerank_enabled',
];

describe('kbChatConfig contract cleanup', () => {
  it('does not serialize removed capability toggles, legacy hybrid knobs, entity expand timeout, or doc gate leftovers', () => {
    const legacyPayload = {
      retrieval_top_k: 9,
      retrieval_hybrid_rrf_k: 72,
      retrieval_hybrid_ranker: 'weighted' as never,
      retrieval_hybrid_dense_weight: 0.7 as never,
      retrieval_hybrid_sparse_weight: 0.3 as never,
      query_rewrite_enabled: false as never,
      ambiguity_check_enabled: false as never,
      normalize_llm_enabled: false as never,
      normalize_alias_max: 6 as never,
      hyde_enabled: false as never,
      entity_expand_enabled: false as never,
      entity_expand_timeout_seconds: 1.2 as never,
      entity_expand_max_candidates: 9 as never,
      entity_expand_max_variants: 6 as never,
      entity_expand_min_confidence: 0.6 as never,
      parallel_retrieval_enabled: false as never,
      doc_gate_rule_threshold: 0.2 as never,
      doc_gate_llm_confidence_floor: 0.3 as never,
      doc_gate_fallback_open_when_evidence_ok: false as never,
      doc_gate_cache_ttl_seconds: 10 as never,
      hybrid_retrieval_enabled: false as never,
      rerank_enabled: false as never,
    } satisfies Partial<KbChatConfig> & Record<string, unknown>;
    const query = toKbGraphSchemaQuery(legacyPayload);

    expect(query).toContain('retrieval_top_k=9');
    expect(query).toContain('retrieval_hybrid_rrf_k=72');
    expect(query).not.toContain('retrieval_hybrid_ranker');
    expect(query).not.toContain('retrieval_hybrid_dense_weight');
    expect(query).not.toContain('retrieval_hybrid_sparse_weight');
    expect(query).not.toContain('entity_expand_max_candidates');
    expect(query).not.toContain('entity_expand_max_variants');
    expect(query).not.toContain('entity_expand_min_confidence');
    for (const key of removedConfigKeys) {
      expect(query).not.toContain(key);
    }
  });
});

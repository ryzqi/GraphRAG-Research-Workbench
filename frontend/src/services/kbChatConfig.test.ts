import { describe, expect, it } from 'vitest';

import type { KbChatConfig } from './chats';
import { toKbGraphSchemaQuery } from './chats';

const removedConfigKeys = [
  'query_rewrite_enabled',
  'ambiguity_check_enabled',
  'normalize_llm_enabled',
  'hyde_enabled',
  'entity_expand_enabled',
  'parallel_retrieval_enabled',
  'doc_gate_rule_threshold',
  'doc_gate_llm_confidence_floor',
  'doc_gate_fallback_open_when_evidence_ok',
  'doc_gate_cache_ttl_seconds',
  'hybrid_retrieval_enabled',
  'rerank_enabled',
];

describe('kbChatConfig contract cleanup', () => {
  it('does not serialize removed capability toggles or doc gate leftovers', () => {
    const legacyPayload = {
      retrieval_top_k: 9,
      retrieval_hybrid_ranker: 'weighted',
      retrieval_hybrid_dense_weight: 0.7,
      query_rewrite_enabled: false as never,
      ambiguity_check_enabled: false as never,
      normalize_llm_enabled: false as never,
      hyde_enabled: false as never,
      entity_expand_enabled: false as never,
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
    expect(query).toContain('retrieval_hybrid_ranker=weighted');
    expect(query).toContain('retrieval_hybrid_dense_weight=0.7');
    for (const key of removedConfigKeys) {
      expect(query).not.toContain(key);
    }
  });
});

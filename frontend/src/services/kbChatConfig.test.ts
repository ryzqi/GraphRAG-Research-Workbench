import { describe, expect, it } from 'vitest';

import type { KbChatConfig } from './chats';
import { validateKbChatConfig } from './kbChatConfig';

function createConfig(overrides: Partial<KbChatConfig> = {}): KbChatConfig {
  return {
    query_rewrite_enabled: true,
    ambiguity_check_enabled: true,
    hyde_enabled: false,
    hybrid_retrieval_enabled: true,
    rerank_enabled: true,
    retrieval_top_k: 8,
    retrieval_rerank_top_k: 50,
    retrieval_hybrid_ranker: 'rrf',
    retrieval_hybrid_dense_weight: 0.7,
    retrieval_hybrid_sparse_weight: 0.3,
    retrieval_hybrid_rrf_k: 60,
    retrieval_parent_max_parents: 6,
    retrieval_parent_max_children_per_parent: 2,
    retrieval_multiscale_per_window_top_k: 30,
    retrieval_multiscale_rrf_k: 60,
    retrieval_multiscale_max_documents: 8,
    retrieval_multiscale_max_chunks_per_document: 2,
    ...overrides,
  };
}

describe('validateKbChatConfig', () => {
  it('accepts a valid config', () => {
    expect(validateKbChatConfig(createConfig())).toEqual([]);
  });

  it('enforces rerank top-k lower bound and weighted sum constraint', () => {
    const errors = validateKbChatConfig(
      createConfig({
        retrieval_rerank_top_k: 3,
        retrieval_hybrid_ranker: 'weighted',
        retrieval_hybrid_dense_weight: 0.8,
        retrieval_hybrid_sparse_weight: 0.1,
      })
    );

    expect(errors).toContain('重排序 Top-K 需在检索 Top-K 与 50 之间。');
    expect(errors).toContain('Weighted 模式下 Dense + BM25 权重之和必须为 1。');
  });
});

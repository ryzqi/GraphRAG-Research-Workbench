import { describe, expect, it } from 'vitest';

import type { KbChatConfig } from './chats';
import { validateKbChatConfig } from './kbChatConfig';

function createConfig(overrides: Partial<KbChatConfig> = {}): KbChatConfig {
  return {
    query_rewrite_enabled: true,
    ambiguity_check_enabled: true,
    decomposition_enabled: true,
    decomposition_max_sub_questions: 3,
    multi_query_enabled: false,
    multi_query_max_variants: 3,
    hyde_enabled: false,
    hybrid_retrieval_enabled: true,
    rerank_enabled: true,
    retrieval_top_k: 5,
    retrieval_rerank_top_k: 20,
    retrieval_hybrid_ranker: 'rrf',
    retrieval_hybrid_dense_weight: 0.7,
    retrieval_hybrid_sparse_weight: 0.3,
    retrieval_hybrid_rrf_k: 60,
    retrieval_parent_max_parents: 6,
    retrieval_parent_max_children_per_parent: 2,
    retrieval_multiscale_per_window_top_k: 20,
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

  it('accepts configs when both decomposition and multi-query are disabled', () => {
    const errors = validateKbChatConfig(
      createConfig({ decomposition_enabled: false, multi_query_enabled: false })
    );

    expect(errors).toEqual([]);
  });

  it('rejects strategy states when both decomposition and multi-query are enabled', () => {
    const errors = validateKbChatConfig(
      createConfig({ decomposition_enabled: true, multi_query_enabled: true })
    );

    expect(errors).toContain('问题分解与多路查询不能同时开启。');
  });

  it('enforces 2~4 range for decomposition and multi-query counts', () => {
    const tooLow = validateKbChatConfig(
      createConfig({ decomposition_max_sub_questions: 1, multi_query_max_variants: 5 })
    );

    expect(tooLow).toContain('问题分解数量需在 2~4。');
    expect(tooLow).toContain('多路查询数量需在 2~4。');
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

    expect(errors).toContain('重排序 Top-K 需在检索 Top-K 与 20 之间。');
    expect(errors).toContain('Weighted 模式下 Dense + BM25 权重之和必须为 1。');
  });
});

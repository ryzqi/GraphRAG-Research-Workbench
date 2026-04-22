import { describe, expect, it } from 'vitest';

import type { KbChatConfig, KbChatConfigConstraints } from './chats';
import { validateKbChatConfig } from './kbChatConfig';

describe('kbChatConfig validation', () => {
  it('keeps the rerank ceiling at 40', () => {
    const constraints: KbChatConfigConstraints = {
      retrieval_top_k: { min: 1, max: 20 },
      retrieval_rerank_top_k: { min: 1, max: 40 },
      retrieval_hybrid_rrf_k: { min: 1, max: 200 },
      retrieval_parent_max_parents: { min: 1, max: 20 },
      retrieval_parent_max_children_per_parent: { min: 1, max: 10 },
      retrieval_multiscale_per_window_top_k: { min: 1, max: 200 },
      retrieval_multiscale_rrf_k: { min: 1, max: 200 },
      retrieval_multiscale_max_documents: { min: 1, max: 100 },
      retrieval_multiscale_max_chunks_per_document: { min: 1, max: 20 },
    };
    const config: KbChatConfig = {
      retrieval_top_k: 12,
      retrieval_rerank_top_k: 40,
      retrieval_hybrid_rrf_k: 60,
      retrieval_parent_max_parents: 8,
      retrieval_parent_max_children_per_parent: 3,
      retrieval_multiscale_per_window_top_k: 40,
      retrieval_multiscale_rrf_k: 60,
      retrieval_multiscale_max_documents: 12,
      retrieval_multiscale_max_chunks_per_document: 2,
    };

    expect(validateKbChatConfig(config, constraints)).toEqual([]);
    expect(
      validateKbChatConfig({
        ...config,
        retrieval_rerank_top_k: 41,
      }, constraints)
    ).toContain('重排序 Top-K 需在检索 Top-K 与 40 之间。');
  });
});

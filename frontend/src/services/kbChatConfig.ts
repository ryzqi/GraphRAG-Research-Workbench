import type { KbChatConfig } from './chats';

export function validateKbChatConfig(value: KbChatConfig): string[] {
  const errors: string[] = [];

  if (value.decomposition_enabled && value.multi_query_enabled) {
    errors.push('问题分解与多路查询不能同时开启。');
  }
  if (value.multi_query_max_variants < 2 || value.multi_query_max_variants > 4) {
    errors.push('多路查询数量需在 2~4。');
  }
  if (value.retrieval_top_k < 1 || value.retrieval_top_k > 20) {
    errors.push('检索 Top-K 需在 1~20。');
  }
  if (value.retrieval_rerank_top_k < value.retrieval_top_k || value.retrieval_rerank_top_k > 20) {
    errors.push('重排序 Top-K 需在检索 Top-K 与 20 之间。');
  }
  if (value.retrieval_hybrid_dense_weight < 0 || value.retrieval_hybrid_dense_weight > 1) {
    errors.push('Dense 权重需在 0~1。');
  }
  if (value.retrieval_hybrid_sparse_weight < 0 || value.retrieval_hybrid_sparse_weight > 1) {
    errors.push('BM25 权重需在 0~1。');
  }
  if (value.retrieval_hybrid_ranker === 'weighted') {
    const total = value.retrieval_hybrid_dense_weight + value.retrieval_hybrid_sparse_weight;
    if (Math.abs(total - 1) > 1e-6) {
      errors.push('Weighted 模式下 Dense + BM25 权重之和必须为 1。');
    }
  }

  return errors;
}

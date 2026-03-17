import type { KbChatConfig } from './chats';

export function validateKbChatConfig(value: KbChatConfig): string[] {
  const errors: string[] = [];

  if (value.retrieval_top_k < 1 || value.retrieval_top_k > 20) {
    errors.push('检索 Top-K 需在 1~20。');
  }
  if (value.retrieval_rerank_top_k < value.retrieval_top_k || value.retrieval_rerank_top_k > 50) {
    errors.push('重排序 Top-K 需在检索 Top-K 与 50 之间。');
  }
  if (value.retrieval_hybrid_rrf_k < 1 || value.retrieval_hybrid_rrf_k > 200) {
    errors.push('Hybrid RRF k 需在 1~200。');
  }

  if (value.entity_expand_max_candidates < 1 || value.entity_expand_max_candidates > 12) {
    errors.push('实体扩展候选上限需在 1~12。');
  }
  if (value.entity_expand_max_variants < 1 || value.entity_expand_max_variants > 12) {
    errors.push('实体扩展输出上限需在 1~12。');
  }
  if (value.entity_expand_max_variants > value.entity_expand_max_candidates) {
    errors.push('实体扩展输出上限不能大于候选上限。');
  }
  if (value.entity_expand_min_confidence < 0 || value.entity_expand_min_confidence > 1) {
    errors.push('实体扩展最小置信度需在 0~1。');
  }

  return errors;
}

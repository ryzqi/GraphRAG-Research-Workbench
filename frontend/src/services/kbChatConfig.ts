import type { KbChatConfig, KbChatConfigConstraints } from './chats';

export function validateKbChatConfig(
  value: KbChatConfig,
  constraints: KbChatConfigConstraints
): string[] {
  const errors: string[] = [];

  if (
    value.retrieval_top_k < constraints.retrieval_top_k.min ||
    value.retrieval_top_k > constraints.retrieval_top_k.max
  ) {
    errors.push(
      `检索 Top-K 需在 ${constraints.retrieval_top_k.min}~${constraints.retrieval_top_k.max}。`
    );
  }
  if (
    value.retrieval_rerank_top_k < value.retrieval_top_k ||
    value.retrieval_rerank_top_k > constraints.retrieval_rerank_top_k.max
  ) {
    errors.push(
      `重排序 Top-K 需在检索 Top-K 与 ${constraints.retrieval_rerank_top_k.max} 之间。`
    );
  }
  if (
    value.retrieval_hybrid_rrf_k < constraints.retrieval_hybrid_rrf_k.min ||
    value.retrieval_hybrid_rrf_k > constraints.retrieval_hybrid_rrf_k.max
  ) {
    errors.push(
      `Hybrid RRF k 需在 ${constraints.retrieval_hybrid_rrf_k.min}~${constraints.retrieval_hybrid_rrf_k.max}。`
    );
  }

  return errors;
}

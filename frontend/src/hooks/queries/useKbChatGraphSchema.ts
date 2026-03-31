import { useApiQuery } from '../../lib/swr';
import {
  getKbChatGraphSchema,
  type KbChatConfig,
  type KbGraphSchema,
} from '../../services/chats';

const KEYS = {
  detail: (config: KbChatConfig) =>
    [
      'kbChatGraphSchema',
      config.retrieval_top_k,
      config.retrieval_rerank_top_k,
      config.retrieval_hybrid_rrf_k,
      config.retrieval_parent_max_parents,
      config.retrieval_parent_max_children_per_parent,
      config.retrieval_multiscale_per_window_top_k,
      config.retrieval_multiscale_rrf_k,
      config.retrieval_multiscale_max_documents,
      config.retrieval_multiscale_max_chunks_per_document,
    ] as const,
};

export function useKbChatGraphSchema(config: KbChatConfig | null) {
  return useApiQuery<KbGraphSchema>(
    config ? KEYS.detail(config) : null,
    config ? () => getKbChatGraphSchema(config) : null,
    {
      skipInitialFetchIfCached: true,
    }
  );
}

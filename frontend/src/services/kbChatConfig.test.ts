import { describe, expect, it } from 'vitest';

import { DEFAULT_KB_CHAT_CONFIG } from './chats';
import { validateKbChatConfig } from './kbChatConfig';

describe('kbChatConfig defaults', () => {
  it('uses the updated rerank default and validation ceiling', () => {
    expect(DEFAULT_KB_CHAT_CONFIG.retrieval_rerank_top_k).toBe(40);

    expect(
      validateKbChatConfig({
        ...DEFAULT_KB_CHAT_CONFIG,
        retrieval_rerank_top_k: 41,
      })
    ).toContain('重排序 Top-K 需在检索 Top-K 与 40 之间。');
  });
});

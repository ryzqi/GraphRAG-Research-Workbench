import { describe, expect, it } from 'vitest';

import { createDefaultIndexConfig } from './knowledgeBases';

describe('createDefaultIndexConfig', () => {
  it('uses the updated semantic embedding batch size', () => {
    expect(createDefaultIndexConfig().chunking.semantic.embedding_batch_size).toBe(32);
  });
});

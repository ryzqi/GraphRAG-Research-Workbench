import { describe, expect, it } from 'vitest';

import { cloneIndexConfig, type IndexConfig } from './knowledgeBases';

describe('cloneIndexConfig', () => {
  it('clones nested index config objects without sharing references', () => {
    const input: IndexConfig = {
      chunking: {
        markdown_heading: {
          max_heading_level: 3,
          chunk_size: 800,
          chunk_overlap: 160,
        },
        general_strategy: 'query_dependent_multiscale',
        query_dependent_multiscale: {
          windows: [
            { chunk_size_tokens: 128, chunk_overlap_tokens: 32 },
            { chunk_size_tokens: 256, chunk_overlap_tokens: 64 },
          ],
        },
        semantic: {
          min_tokens: 80,
          max_tokens: 320,
          threshold_mode: 'percentile',
          breakpoint_percentile: 25,
          similarity_threshold: 0.7,
          overlap_chars: 96,
          embedding_batch_size: 32,
        },
        parent_child: {
          parent: {
            chunk_size: 1200,
            chunk_overlap: 120,
          },
          child: {
            chunk_size: 240,
            chunk_overlap: 40,
          },
        },
      },
      contextual: {
        enabled: true,
        max_tokens: 192,
        concurrency: 2,
      },
    };

    const cloned = cloneIndexConfig(input);
    expect(cloned.chunking.semantic.embedding_batch_size).toBe(32);
    expect(cloned).toEqual(input);
    expect(cloned).not.toBe(input);
    expect(cloned.chunking).not.toBe(input.chunking);
    expect(cloned.chunking.query_dependent_multiscale.windows).not.toBe(
      input.chunking.query_dependent_multiscale.windows
    );
  });
});

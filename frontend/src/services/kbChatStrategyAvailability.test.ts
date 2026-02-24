import { describe, expect, it } from 'vitest';

import type { ChunkingStrategy, KnowledgeBase } from './knowledgeBases';
import { hasSelectedParentChildKnowledgeBase } from './kbChatStrategyAvailability';

function createKnowledgeBase(id: string, strategy: ChunkingStrategy): KnowledgeBase {
  return {
    id,
    name: `KB-${id}`,
    description: null,
    tags: [],
    status: 'active',
    readiness: 'ready',
    readiness_updated_at: '2026-02-17T00:00:00.000Z',
    current_config_version: 1,
    index_config: {
      chunking: {
        markdown_heading: {
          max_heading_level: 3,
          chunk_size: 800,
          chunk_overlap: 160,
        },
        general_strategy: strategy,
        query_dependent_multiscale: {
          windows: [{ chunk_size_tokens: 128, chunk_overlap_tokens: 32 }],
        },
        semantic: {
          min_tokens: 80,
          max_tokens: 320,
          threshold_mode: 'percentile',
          breakpoint_percentile: 25,
          similarity_threshold: 0.7,
          overlap_chars: 96,
          embedding_batch_size: 64,
        },
        parent_child: {
          parent: { chunk_size: 1200, chunk_overlap: 120 },
          child: { chunk_size: 240, chunk_overlap: 40 },
        },
      },
      contextual: {
        enabled: true,
        max_tokens: 192,
        concurrency: 2,
      },
    },
    created_at: '2026-02-17T00:00:00.000Z',
    updated_at: '2026-02-17T00:00:00.000Z',
  };
}

describe('hasSelectedParentChildKnowledgeBase', () => {
  it('returns true when any selected knowledge base uses parent_child chunking', () => {
    const kbs = [
      createKnowledgeBase('kb-a', 'query_dependent_multiscale'),
      createKnowledgeBase('kb-b', 'parent_child'),
    ];

    expect(hasSelectedParentChildKnowledgeBase(['kb-a', 'kb-b'], kbs)).toBe(true);
  });

  it('returns false when selected knowledge bases do not use parent_child chunking', () => {
    const kbs = [
      createKnowledgeBase('kb-a', 'query_dependent_multiscale'),
      createKnowledgeBase('kb-b', 'max_min_semantic'),
    ];

    expect(hasSelectedParentChildKnowledgeBase(['kb-a', 'kb-b'], kbs)).toBe(false);
  });

  it('returns false for empty or missing input data', () => {
    expect(hasSelectedParentChildKnowledgeBase([], [])).toBe(false);
    expect(hasSelectedParentChildKnowledgeBase(['kb-a'], undefined)).toBe(false);
    expect(hasSelectedParentChildKnowledgeBase(['kb-a'], [createKnowledgeBase('kb-b', 'parent_child')])).toBe(
      false
    );
  });
});

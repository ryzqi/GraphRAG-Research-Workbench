import { describe, expect, it, vi } from 'vitest';

import type {
  DocumentChunk,
  DocumentChunkListResponse,
} from './materialChunks';
import {
  fetchAllMaterialChunks,
  groupChunksForBrowser,
} from './materialChunkBrowser';

function makeChunk(
  overrides: Partial<DocumentChunk> & Pick<DocumentChunk, 'id' | 'chunk_index'>
): DocumentChunk {
  return {
    id: overrides.id,
    kb_id: overrides.kb_id ?? 'kb-1',
    material_id: overrides.material_id ?? 'mat-1',
    chunk_index: overrides.chunk_index,
    raw_text: overrides.raw_text ?? `chunk-${overrides.id}`,
    embedding_text: overrides.embedding_text ?? `embedding-${overrides.id}`,
    context_text: overrides.context_text ?? null,
    context_status: overrides.context_status ?? 'success',
    context_error: overrides.context_error ?? null,
    context_attempts: overrides.context_attempts ?? 0,
    chunking_strategy:
      overrides.chunking_strategy ?? 'query_dependent_multiscale',
    heading_path: overrides.heading_path ?? null,
    window_id: overrides.window_id ?? null,
    window_size_tokens: overrides.window_size_tokens ?? null,
    window_overlap_tokens: overrides.window_overlap_tokens ?? null,
    token_start: overrides.token_start ?? null,
    token_end: overrides.token_end ?? null,
    locator: overrides.locator ?? null,
    token_count: overrides.token_count ?? null,
    created_at: overrides.created_at ?? '2026-03-11T00:00:00Z',
  };
}

function makePage(
  items: DocumentChunk[],
  page: Partial<DocumentChunkListResponse['page']> = {}
): DocumentChunkListResponse {
  return {
    items,
    page: {
      skip: page.skip ?? 0,
      limit: page.limit ?? 100,
      total: page.total ?? items.length,
      has_more: page.has_more ?? false,
    },
  };
}

describe('fetchAllMaterialChunks', () => {
  it('keeps requesting pages until all chunks are loaded', async () => {
    const listPage = vi
      .fn<(skip: number, limit: number) => Promise<DocumentChunkListResponse>>()
      .mockImplementation(async (skip, limit) => {
        if (skip === 0) {
          expect(limit).toBe(100);
          return makePage(
            [
              makeChunk({
                id: 'chunk-256-a',
                chunk_index: 0,
                window_size_tokens: 256,
                token_start: 0,
              }),
              makeChunk({
                id: 'chunk-256-b',
                chunk_index: 1,
                window_size_tokens: 256,
                token_start: 192,
              }),
            ],
            { skip, limit, total: 4, has_more: true }
          );
        }

        if (skip === 2) {
          return makePage(
            [
              makeChunk({
                id: 'chunk-512-a',
                chunk_index: 2,
                window_size_tokens: 512,
                token_start: 0,
              }),
              makeChunk({
                id: 'chunk-512-b',
                chunk_index: 3,
                window_size_tokens: 512,
                token_start: 384,
              }),
            ],
            { skip, limit, total: 4, has_more: false }
          );
        }

        throw new Error(`unexpected skip ${skip}`);
      });

    const chunks = await fetchAllMaterialChunks('kb-1', 'mat-1', {
      listPage: async (_kbId, _materialId, params) =>
        listPage(params?.skip ?? 0, params?.limit ?? 100),
    });

    expect(listPage).toHaveBeenCalledTimes(2);
    expect(chunks.map((chunk) => chunk.id)).toEqual([
      'chunk-256-a',
      'chunk-256-b',
      'chunk-512-a',
      'chunk-512-b',
    ]);
  });
});

describe('groupChunksForBrowser', () => {
  it('groups multiscale chunks by window_size_tokens and keeps full membership', () => {
    const groups = groupChunksForBrowser([
      makeChunk({
        id: 'chunk-512-b',
        chunk_index: 103,
        window_size_tokens: 512,
        token_start: 384,
      }),
      makeChunk({
        id: 'chunk-256-b',
        chunk_index: 1,
        window_size_tokens: 256,
        token_start: 192,
      }),
      makeChunk({
        id: 'chunk-512-a',
        chunk_index: 102,
        window_size_tokens: 512,
        token_start: 0,
      }),
      makeChunk({
        id: 'chunk-256-a',
        chunk_index: 0,
        window_size_tokens: 256,
        token_start: 0,
      }),
    ]);

    expect(groups.map((group) => group.label)).toEqual([
      '256 tokens',
      '512 tokens',
    ]);
    expect(groups.map((group) => group.items.map((chunk) => chunk.id))).toEqual([
      ['chunk-256-a', 'chunk-256-b'],
      ['chunk-512-a', 'chunk-512-b'],
    ]);
  });
});

import { describe, expect, it, vi } from 'vitest';

import type {
  DocumentChunk,
  MaterialWithChunkStatsListResponse,
  SourceMaterialWithChunkStats,
} from './materialChunks';
import {
  buildKnowledgeBaseDetailTabs,
  fetchAllMaterialsWithChunkStats,
  resolveActiveChunkId,
  resolveActiveKey,
  summarizeKnowledgeBaseInventory,
} from './knowledgeBaseDetailLayout';

function makeMaterial(
  overrides: Partial<SourceMaterialWithChunkStats> & Pick<SourceMaterialWithChunkStats, 'id'>
): SourceMaterialWithChunkStats {
  return {
    id: overrides.id,
    kb_id: overrides.kb_id ?? 'kb-1',
    source_type: overrides.source_type ?? 'upload',
    title: overrides.title ?? overrides.id,
    uri: overrides.uri ?? null,
    mime_type: overrides.mime_type ?? null,
    created_at: overrides.created_at ?? '2026-03-11T00:00:00Z',
    updated_at: overrides.updated_at ?? '2026-03-11T00:00:00Z',
    chunk_count: overrides.chunk_count ?? 0,
  };
}

function makeMaterialPage(
  items: SourceMaterialWithChunkStats[],
  page: Partial<MaterialWithChunkStatsListResponse['page']> = {}
): MaterialWithChunkStatsListResponse {
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

function makeChunk(
  overrides: Partial<DocumentChunk> & Pick<DocumentChunk, 'id' | 'chunk_index'>
): DocumentChunk {
  return {
    id: overrides.id,
    kb_id: overrides.kb_id ?? 'kb-1',
    material_id: overrides.material_id ?? 'mat-1',
    chunk_index: overrides.chunk_index,
    raw_text: overrides.raw_text ?? overrides.id,
    embedding_text: overrides.embedding_text ?? overrides.id,
    context_text: overrides.context_text ?? null,
    context_status: overrides.context_status ?? 'success',
    context_error: overrides.context_error ?? null,
    context_attempts: overrides.context_attempts ?? 0,
    chunking_strategy:
      overrides.chunking_strategy ?? 'query_dependent_multiscale',
    heading_path: overrides.heading_path ?? null,
    global_chunk_order: overrides.global_chunk_order,
    window_id: overrides.window_id ?? null,
    window_size_tokens: overrides.window_size_tokens ?? null,
    window_overlap_tokens: overrides.window_overlap_tokens ?? null,
    token_start: overrides.token_start ?? null,
    token_end: overrides.token_end ?? null,
    source_kind: overrides.source_kind ?? null,
    source_page_start: overrides.source_page_start ?? null,
    source_page_end: overrides.source_page_end ?? null,
    locator: overrides.locator ?? null,
    token_count: overrides.token_count ?? null,
    created_at: overrides.created_at ?? '2026-03-11T00:00:00Z',
  };
}

describe('fetchAllMaterialsWithChunkStats', () => {
  it('keeps requesting pages until all materials are loaded', async () => {
    const listPage = vi
      .fn<(skip: number, limit: number) => Promise<MaterialWithChunkStatsListResponse>>()
      .mockImplementation(async (skip, limit) => {
        if (skip === 0) {
          expect(limit).toBe(100);
          return makeMaterialPage(
            [
              makeMaterial({ id: 'doc-1', chunk_count: 8 }),
              makeMaterial({ id: 'doc-2', chunk_count: 12 }),
            ],
            { skip, limit, total: 4, has_more: true }
          );
        }

        if (skip === 2) {
          return makeMaterialPage(
            [
              makeMaterial({ id: 'doc-3', chunk_count: 20 }),
              makeMaterial({ id: 'doc-4', chunk_count: 16 }),
            ],
            { skip, limit, total: 4, has_more: false }
          );
        }

        throw new Error(`unexpected skip ${skip}`);
      });

    const materials = await fetchAllMaterialsWithChunkStats('kb-1', {
      listPage: async (_kbId, params) =>
        listPage(params?.skip ?? 0, params?.limit ?? 100),
    });

    expect(listPage).toHaveBeenCalledTimes(2);
    expect(materials.map((material) => material.id)).toEqual([
      'doc-1',
      'doc-2',
      'doc-3',
      'doc-4',
    ]);
  });
});

describe('summarizeKnowledgeBaseInventory', () => {
  it('aggregates document and chunk totals from all loaded materials', () => {
    expect(
      summarizeKnowledgeBaseInventory([
        makeMaterial({ id: 'doc-1', chunk_count: 8 }),
        makeMaterial({ id: 'doc-2', chunk_count: 12 }),
        makeMaterial({ id: 'doc-3', chunk_count: 0 }),
      ])
    ).toEqual({
      documentCount: 3,
      chunkCount: 20,
    });
  });
});

describe('detail selection helpers', () => {
  it('keeps active group order stable for 3 and 4 multiscale windows', () => {
    const tabs = buildKnowledgeBaseDetailTabs([
      makeChunk({
        id: 'chunk-1024',
        chunk_index: 5,
        window_size_tokens: 1024,
        token_start: 0,
      }),
      makeChunk({
        id: 'chunk-256',
        chunk_index: 0,
        window_size_tokens: 256,
        token_start: 0,
      }),
      makeChunk({
        id: 'chunk-2048',
        chunk_index: 9,
        window_size_tokens: 2048,
        token_start: 0,
      }),
      makeChunk({
        id: 'chunk-512',
        chunk_index: 2,
        window_size_tokens: 512,
        token_start: 0,
      }),
    ]);

    expect(tabs.map((tab) => tab.label)).toEqual([
      '256 tokens',
      '512 tokens',
      '1024 tokens',
      '2048 tokens',
    ]);
    expect(resolveActiveKey(tabs, 'window:1024')).toBe('window:1024');
    expect(resolveActiveKey(tabs, 'window:missing')).toBe('window:256');
  });

  it('falls back to the first available chunk in the active group', () => {
    expect(
      resolveActiveChunkId(
        [
          makeChunk({ id: 'chunk-a', chunk_index: 0 }),
          makeChunk({ id: 'chunk-b', chunk_index: 1 }),
        ],
        'missing-id'
      )
    ).toBe('chunk-a');
  });
});

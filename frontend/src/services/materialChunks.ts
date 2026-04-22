/**
 * Material chunk browsing APIs
 */

import { apiFetch, apiV1Path } from './http';
import type { SourceMaterial } from './materials';
import type { ListResponse } from './types';

export interface SourceMaterialWithChunkStats extends SourceMaterial {
  chunk_count: number;
}

export type MaterialWithChunkStatsListResponse = ListResponse<SourceMaterialWithChunkStats>;

export interface DocumentChunk {
  id: string;
  kb_id: string;
  material_id: string;
  chunk_index: number;
  raw_text: string;
  embedding_text: string;
  context_text: string | null;
  context_status: string;
  context_error: string | null;
  context_attempts: number;
  chunking_strategy: string;
  heading_path: string | null;
  global_chunk_order?: number;
  window_id: number | null;
  window_size_tokens: number | null;
  window_overlap_tokens: number | null;
  token_start: number | null;
  token_end: number | null;
  source_kind?: string | null;
  source_page_start?: number | null;
  source_page_end?: number | null;
  locator: Record<string, unknown> | null;
  token_count: number | null;
  created_at: string;
}

export type DocumentChunkListResponse = ListResponse<DocumentChunk>;

interface PaginationParams {
  skip?: number;
  limit?: number;
}

function withPagination(path: string, params?: PaginationParams): string {
  if (!params) {
    return path;
  }
  const qs = new URLSearchParams();
  if (typeof params.skip === 'number') {
    qs.set('skip', String(params.skip));
  }
  if (typeof params.limit === 'number') {
    qs.set('limit', String(params.limit));
  }
  const query = qs.toString();
  return query ? `${path}?${query}` : path;
}

export async function listMaterialsWithChunkStats(
  kbId: string,
  params?: PaginationParams
): Promise<MaterialWithChunkStatsListResponse> {
  const path = withPagination(apiV1Path(`/knowledge-bases/${kbId}/materials/with-chunk-stats`), params);
  return apiFetch<MaterialWithChunkStatsListResponse>(path);
}

export async function listMaterialChunks(
  kbId: string,
  materialId: string,
  params?: PaginationParams
): Promise<DocumentChunkListResponse> {
  const path = withPagination(
    apiV1Path(`/knowledge-bases/${kbId}/materials/${materialId}/chunks`),
    params
  );
  return apiFetch<DocumentChunkListResponse>(path);
}

export async function getMaterialChunk(
  kbId: string,
  materialId: string,
  chunkId: string
): Promise<DocumentChunk> {
  return apiFetch<DocumentChunk>(
    apiV1Path(`/knowledge-bases/${kbId}/materials/${materialId}/chunks/${chunkId}`)
  );
}

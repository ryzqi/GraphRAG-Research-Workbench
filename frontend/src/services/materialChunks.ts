/**
 * Material chunk browsing APIs
 */

import { apiFetch } from './http';
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
  const path = withPagination(`/api/v1/knowledge-bases/${kbId}/materials/with-chunk-stats`, params);
  return apiFetch<MaterialWithChunkStatsListResponse>(path);
}

export async function listMaterialChunks(
  kbId: string,
  materialId: string,
  params?: PaginationParams
): Promise<DocumentChunkListResponse> {
  const path = withPagination(
    `/api/v1/knowledge-bases/${kbId}/materials/${materialId}/chunks`,
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
    `/api/v1/knowledge-bases/${kbId}/materials/${materialId}/chunks/${chunkId}`
  );
}

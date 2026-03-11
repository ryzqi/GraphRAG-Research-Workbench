/**
 * Material chunk browsing hooks based on SWR
 */
import {
  getMaterialChunk,
  listMaterialChunks,
  listMaterialsWithChunkStats,
} from '../../services/materialChunks';
import { fetchAllMaterialChunks } from '../../services/materialChunkBrowser';
import { fetchAllMaterialsWithChunkStats } from '../../services/knowledgeBaseDetailLayout';
import { useApiQuery } from '../../lib/swr';

const NO_ID = '__none__';

interface PaginationParams {
  skip?: number;
  limit?: number;
}

interface QueryOptions {
  enabled?: boolean;
}

const KEYS = {
  all: ['materialChunks'] as const,
  materials: (kbId: string) => [...KEYS.all, 'materials', kbId || NO_ID] as const,
  materialsAll: (kbId: string, limit: number) =>
    [...KEYS.all, 'materialsAll', kbId || NO_ID, limit] as const,
  chunks: (
    kbId: string,
    materialId: string,
    skip: number,
    limit: number
  ) => [...KEYS.all, 'chunks', kbId || NO_ID, materialId || NO_ID, skip, limit] as const,
  chunksAll: (kbId: string, materialId: string, limit: number) =>
    [...KEYS.all, 'chunksAll', kbId || NO_ID, materialId || NO_ID, limit] as const,
  chunkDetail: (kbId: string, materialId: string, chunkId: string) =>
    [...KEYS.all, 'chunkDetail', kbId || NO_ID, materialId || NO_ID, chunkId || NO_ID] as const,
};

export function useMaterialsWithChunkStats(kbId: string, params?: PaginationParams) {
  const skip = params?.skip ?? 0;
  const limit = params?.limit ?? 100;
  return useApiQuery(
    kbId ? KEYS.materials(kbId) : null,
    kbId
      ? () => listMaterialsWithChunkStats(kbId, { skip, limit }).then((res) => res.items)
      : null
  );
}

export function useMaterialChunks(
  kbId: string,
  materialId: string,
  params?: PaginationParams & QueryOptions
) {
  const skip = params?.skip ?? 0;
  const limit = params?.limit ?? 100;
  const enabled = params?.enabled ?? true;
  return useApiQuery(
    kbId && materialId && enabled ? KEYS.chunks(kbId, materialId, skip, limit) : null,
    kbId && materialId && enabled
      ? () => listMaterialChunks(kbId, materialId, { skip, limit }).then((res) => res.items)
      : null
  );
}

export function useAllMaterialsWithChunkStats(
  kbId: string,
  params?: PaginationParams & QueryOptions
) {
  const limit = params?.limit ?? 100;
  const enabled = params?.enabled ?? true;
  return useApiQuery(
    kbId && enabled ? KEYS.materialsAll(kbId, limit) : null,
    kbId && enabled ? () => fetchAllMaterialsWithChunkStats(kbId, { limit }) : null
  );
}

export function useAllMaterialChunks(
  kbId: string,
  materialId: string,
  params?: PaginationParams & QueryOptions
) {
  const limit = params?.limit ?? 100;
  const enabled = params?.enabled ?? true;
  return useApiQuery(
    kbId && materialId && enabled ? KEYS.chunksAll(kbId, materialId, limit) : null,
    kbId && materialId && enabled
      ? () => fetchAllMaterialChunks(kbId, materialId, { limit })
      : null
  );
}

export function useMaterialChunkDetail(
  kbId: string,
  materialId: string,
  chunkId: string | null,
  options?: QueryOptions
) {
  const enabled = options?.enabled ?? true;
  return useApiQuery(
    kbId && materialId && chunkId && enabled ? KEYS.chunkDetail(kbId, materialId, chunkId) : null,
    kbId && materialId && chunkId && enabled
      ? () => getMaterialChunk(kbId, materialId, chunkId)
      : null
  );
}

export { KEYS as materialChunkKeys };

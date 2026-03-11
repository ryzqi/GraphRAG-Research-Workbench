import type {
  DocumentChunk,
  MaterialWithChunkStatsListResponse,
  SourceMaterialWithChunkStats,
} from './materialChunks';
import { listMaterialsWithChunkStats } from './materialChunks';
import {
  groupChunksForBrowser,
  type MaterialChunkBrowserGroup,
} from './materialChunkBrowser';

interface PaginationParams {
  skip?: number;
  limit?: number;
}

interface FetchAllMaterialsWithChunkStatsOptions {
  limit?: number;
  listPage?: (
    kbId: string,
    params?: PaginationParams
  ) => Promise<MaterialWithChunkStatsListResponse>;
}

export interface KnowledgeBaseWorkspaceModel {
  windows: MaterialChunkBrowserGroup[];
  defaultWindowKey: string | null;
}

const DEFAULT_PAGE_LIMIT = 100;

export async function fetchAllMaterialsWithChunkStats(
  kbId: string,
  options?: FetchAllMaterialsWithChunkStatsOptions
): Promise<SourceMaterialWithChunkStats[]> {
  const limit = Math.max(1, options?.limit ?? DEFAULT_PAGE_LIMIT);
  const listPage = options?.listPage ?? listMaterialsWithChunkStats;
  const materials: SourceMaterialWithChunkStats[] = [];
  const seenMaterialIds = new Set<string>();

  let skip = 0;
  while (true) {
    const response = await listPage(kbId, { skip, limit });
    for (const material of response.items) {
      if (seenMaterialIds.has(material.id)) {
        continue;
      }
      seenMaterialIds.add(material.id);
      materials.push(material);
    }

    if (!response.page.has_more || response.items.length === 0) {
      break;
    }

    skip = response.page.skip + response.items.length;
  }

  return materials;
}

export function summarizeKnowledgeBaseInventory(
  materials: SourceMaterialWithChunkStats[]
): {
  documentCount: number;
  chunkCount: number;
} {
  return {
    documentCount: materials.length,
    chunkCount: materials.reduce(
      (total, material) => total + Math.max(material.chunk_count ?? 0, 0),
      0
    ),
  };
}

export function summarizeMaterialStats(
  materials: SourceMaterialWithChunkStats[]
): {
  documentCount: number;
  chunkCount: number;
} {
  return summarizeKnowledgeBaseInventory(materials);
}

export function buildKnowledgeBaseDetailTabs(
  chunks: DocumentChunk[]
): MaterialChunkBrowserGroup[] {
  return groupChunksForBrowser(chunks);
}

export function resolveActiveKey(
  windows: MaterialChunkBrowserGroup[],
  requestedKey: string | null | undefined
): string | null {
  if (!windows.length) {
    return null;
  }
  if (requestedKey && windows.some((window) => window.key === requestedKey)) {
    return requestedKey;
  }
  return windows[0].key;
}

export function resolveActiveChunkId(
  chunks: DocumentChunk[],
  requestedChunkId: string | null | undefined
): string | null {
  if (!chunks.length) {
    return null;
  }
  if (requestedChunkId && chunks.some((chunk) => chunk.id === requestedChunkId)) {
    return requestedChunkId;
  }
  return chunks[0].id;
}

export function buildKnowledgeBaseWorkspaceModel(
  chunks: DocumentChunk[]
): KnowledgeBaseWorkspaceModel {
  const windows = buildKnowledgeBaseDetailTabs(chunks);
  return {
    windows,
    defaultWindowKey: resolveActiveKey(windows, null),
  };
}

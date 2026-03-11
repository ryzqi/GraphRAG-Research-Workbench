import type {
  DocumentChunk,
  DocumentChunkListResponse,
} from './materialChunks';
import { listMaterialChunks } from './materialChunks';

export interface MaterialChunkBrowserGroup {
  key: string;
  label: string;
  items: DocumentChunk[];
  windowSizeTokens: number | null;
}

interface PaginationParams {
  skip?: number;
  limit?: number;
}

interface FetchAllMaterialChunksOptions {
  limit?: number;
  listPage?: (
    kbId: string,
    materialId: string,
    params?: PaginationParams
  ) => Promise<DocumentChunkListResponse>;
}

const DEFAULT_PAGE_LIMIT = 100;
const UNKNOWN_WINDOW_SORT_ORDER = Number.MAX_SAFE_INTEGER - 1;
const NON_WINDOW_SORT_ORDER = Number.MAX_SAFE_INTEGER;

function normalizeChunkStrategy(chunk: DocumentChunk): string {
  const direct = chunk.chunking_strategy?.trim();
  if (direct) {
    return direct;
  }
  const locatorStrategy = chunk.locator?.chunking_strategy;
  return typeof locatorStrategy === 'string' && locatorStrategy.trim()
    ? locatorStrategy.trim()
    : 'unknown';
}

function chunkStrategyLabel(strategy: string): string {
  switch (strategy) {
    case 'query_dependent_multiscale':
      return '多尺度窗口';
    case 'markdown_heading':
      return 'Markdown 标题';
    case 'max_min_semantic':
      return '语义分块';
    case 'parent_child':
      return '父子子块';
    case 'parent_window':
      return '父子父块';
    default:
      return strategy || '未知策略';
  }
}

function locatorNumber(chunk: DocumentChunk, key: string): number | null {
  const rawValue = chunk.locator?.[key];
  if (typeof rawValue === 'number' && Number.isFinite(rawValue)) {
    return rawValue;
  }
  if (typeof rawValue === 'string') {
    const parsed = Number(rawValue);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function resolveChunkWindowSizeTokens(chunk: DocumentChunk): number | null {
  if (
    typeof chunk.window_size_tokens === 'number' &&
    Number.isFinite(chunk.window_size_tokens)
  ) {
    return chunk.window_size_tokens;
  }
  return locatorNumber(chunk, 'window_size_tokens');
}

function resolveChunkTokenStart(chunk: DocumentChunk): number | null {
  if (typeof chunk.token_start === 'number' && Number.isFinite(chunk.token_start)) {
    return chunk.token_start;
  }
  return locatorNumber(chunk, 'token_start');
}

function compareNullableNumbers(
  left: number | null,
  right: number | null
): number {
  if (left == null && right == null) {
    return 0;
  }
  if (left == null) {
    return 1;
  }
  if (right == null) {
    return -1;
  }
  return left - right;
}

function compareChunksWithinGroup(left: DocumentChunk, right: DocumentChunk): number {
  return (
    compareNullableNumbers(resolveChunkTokenStart(left), resolveChunkTokenStart(right)) ||
    left.chunk_index - right.chunk_index ||
    left.id.localeCompare(right.id)
  );
}

function buildGroupMeta(chunk: DocumentChunk): {
  key: string;
  label: string;
  sortOrder: number;
  windowSizeTokens: number | null;
} {
  const strategy = normalizeChunkStrategy(chunk);
  if (strategy === 'query_dependent_multiscale') {
    const windowSizeTokens = resolveChunkWindowSizeTokens(chunk);
    if (windowSizeTokens != null) {
      return {
        key: `window:${windowSizeTokens}`,
        label: `${windowSizeTokens} tokens`,
        sortOrder: windowSizeTokens,
        windowSizeTokens,
      };
    }
    return {
      key: 'window:unknown',
      label: '未知窗口',
      sortOrder: UNKNOWN_WINDOW_SORT_ORDER,
      windowSizeTokens: null,
    };
  }

  return {
    key: `strategy:${strategy}`,
    label: chunkStrategyLabel(strategy),
    sortOrder: NON_WINDOW_SORT_ORDER,
    windowSizeTokens: null,
  };
}

export async function fetchAllMaterialChunks(
  kbId: string,
  materialId: string,
  options?: FetchAllMaterialChunksOptions
): Promise<DocumentChunk[]> {
  const limit = Math.max(1, options?.limit ?? DEFAULT_PAGE_LIMIT);
  const listPage = options?.listPage ?? listMaterialChunks;
  const chunks: DocumentChunk[] = [];
  const seenChunkIds = new Set<string>();

  let skip = 0;
  while (true) {
    const response = await listPage(kbId, materialId, { skip, limit });
    for (const chunk of response.items) {
      if (seenChunkIds.has(chunk.id)) {
        continue;
      }
      seenChunkIds.add(chunk.id);
      chunks.push(chunk);
    }

    if (!response.page.has_more || response.items.length === 0) {
      break;
    }

    skip = response.page.skip + response.items.length;
  }

  return chunks;
}

export function groupChunksForBrowser(
  chunks: DocumentChunk[]
): MaterialChunkBrowserGroup[] {
  const groups = new Map<
    string,
    {
      label: string;
      items: DocumentChunk[];
      sortOrder: number;
      windowSizeTokens: number | null;
    }
  >();

  for (const chunk of chunks) {
    const meta = buildGroupMeta(chunk);
    const current = groups.get(meta.key);
    if (current) {
      current.items.push(chunk);
      continue;
    }
    groups.set(meta.key, {
      label: meta.label,
      items: [chunk],
      sortOrder: meta.sortOrder,
      windowSizeTokens: meta.windowSizeTokens,
    });
  }

  return [...groups.entries()]
    .sort((left, right) => {
      const leftGroup = left[1];
      const rightGroup = right[1];
      return (
        leftGroup.sortOrder - rightGroup.sortOrder ||
        leftGroup.label.localeCompare(rightGroup.label)
      );
    })
    .map(([key, group]) => ({
      key,
      label: group.label,
      windowSizeTokens: group.windowSizeTokens,
      items: [...group.items].sort(compareChunksWithinGroup),
    }));
}

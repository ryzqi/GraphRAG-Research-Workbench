/**
 * 知识库 API 封装
 */

import { apiFetch, type ApiFetchOptions } from './http';
import type { BatchStatus } from './ingestionBatches';
import type { IndexRebuildJob } from './indexRebuilds';
import type { ListResponse } from './types';

export type ChunkingStrategy =
  | 'query_dependent_multiscale'
  | 'max_min_semantic'
  | 'parent_child'
  | 'markdown_heading';

export interface MarkdownHeadingConfig {
  max_heading_level: number;
  chunk_size: number;
  chunk_overlap: number;
}

export interface QueryDependentMultiscaleWindowConfig {
  chunk_size_tokens: number;
  chunk_overlap_tokens: number;
}

export interface QueryDependentMultiscaleChunkingConfig {
  windows: QueryDependentMultiscaleWindowConfig[];
}

export type SemanticThresholdMode = 'percentile' | 'hybrid' | 'fixed';

export interface SemanticConfig {
  min_tokens: number;
  max_tokens: number;
  threshold_mode: SemanticThresholdMode;
  breakpoint_percentile: number | null;
  similarity_threshold: number | null;
  overlap_chars: number;
  embedding_batch_size: number;
}

export interface ParentChunkConfig {
  chunk_size: number;
  chunk_overlap: number;
}

export interface ChildChunkConfig {
  chunk_size: number;
  chunk_overlap: number;
}

export interface ParentChildConfig {
  parent: ParentChunkConfig;
  child: ChildChunkConfig;
}

export interface ChunkingConfig {
  markdown_heading: MarkdownHeadingConfig;
  general_strategy: ChunkingStrategy;
  query_dependent_multiscale: QueryDependentMultiscaleChunkingConfig;
  semantic: SemanticConfig;
  parent_child: ParentChildConfig;
}

export interface ContextualConfig {
  enabled: boolean;
  max_tokens: number;
  concurrency: number;
}

export interface IndexConfig {
  chunking: ChunkingConfig;
  contextual: ContextualConfig;
}

export type KnowledgeBaseReadiness = 'not_ready' | 'ready';

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  tags: string[] | null;
  status: 'active' | 'archived';
  readiness: KnowledgeBaseReadiness;
  readiness_updated_at: string;
  current_config_version: number;
  index_config: IndexConfig | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeBaseIngestionState {
  kb_id: string;
  has_active_batch: boolean;
  active_batch_id: string | null;
  active_batch_status: BatchStatus | null;
  updated_at: string;
}

export type KnowledgeBaseListResponse = ListResponse<KnowledgeBase>;
export type KnowledgeBaseStatusFilter = 'active' | 'archived' | 'all';
export type KnowledgeBaseReadinessFilter = 'ready' | 'not_ready' | 'all';

export interface KnowledgeBaseCreate {
  name: string;
  description?: string;
  tags?: string[];
  index_config: IndexConfig;
}

export interface KnowledgeBaseUpdate {
  name?: string;
  description?: string;
  tags?: string[];
}

export interface KnowledgeBaseIndexConfigUpdateResponse {
  knowledge_base: KnowledgeBase;
  rebuild_job: IndexRebuildJob | null;
}

export function createDefaultIndexConfig(): IndexConfig {
  return {
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
          { chunk_size_tokens: 512, chunk_overlap_tokens: 128 },
        ],
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
}

/**
 * 获取知识库列表
 */
export async function listKnowledgeBases(params?: {
  status?: KnowledgeBaseStatusFilter;
  readiness?: KnowledgeBaseReadinessFilter;
  skip?: number;
  limit?: number;
}): Promise<KnowledgeBaseListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.status) {
    searchParams.set('status', params.status);
  }
  if (params?.readiness) {
    searchParams.set('readiness', params.readiness);
  }
  if (params?.skip !== undefined) {
    searchParams.set('skip', String(params.skip));
  }
  if (params?.limit !== undefined) {
    searchParams.set('limit', String(params.limit));
  }
  const query = searchParams.toString();
  return apiFetch<KnowledgeBaseListResponse>(
    '/api/v1/knowledge-bases' + (query ? '?' + query : '')
  );
}

/**
 * 业务入口口径：仅获取 active + ready 知识库
 */
export async function listSelectableKnowledgeBases(params?: {
  skip?: number;
  limit?: number;
}, options?: ApiFetchOptions): Promise<KnowledgeBaseListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.skip !== undefined) {
    searchParams.set('skip', String(params.skip));
  }
  if (params?.limit !== undefined) {
    searchParams.set('limit', String(params.limit));
  }
  const query = searchParams.toString();
  return apiFetch<KnowledgeBaseListResponse>(
    '/api/v1/knowledge-bases/selectable' + (query ? '?' + query : ''),
    options
  );
}

/**
 * 获取知识库详情
 */
export async function getKnowledgeBase(
  kbId: string,
  options?: ApiFetchOptions
): Promise<KnowledgeBase> {
  return apiFetch<KnowledgeBase>('/api/v1/knowledge-bases/' + kbId, options);
}

/**
 * 获取知识库 ingestion 状态
 */
export async function getKnowledgeBaseIngestionState(
  kbId: string,
  options?: ApiFetchOptions
): Promise<KnowledgeBaseIngestionState> {
  return apiFetch<KnowledgeBaseIngestionState>(
    '/api/v1/knowledge-bases/' + kbId + '/ingestion-state',
    options
  );
}

/**
 * 创建知识库
 */
export async function createKnowledgeBase(
  data: KnowledgeBaseCreate
): Promise<KnowledgeBase> {
  return apiFetch<KnowledgeBase>('/api/v1/knowledge-bases', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 更新知识库
 */
export async function updateKnowledgeBase(
  kbId: string,
  data: KnowledgeBaseUpdate
): Promise<KnowledgeBase> {
  return apiFetch<KnowledgeBase>('/api/v1/knowledge-bases/' + kbId, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

/**
 * 更新知识库索引配置（触发重建）
 */
export async function updateKnowledgeBaseIndexConfig(
  kbId: string,
  index_config: IndexConfig
): Promise<KnowledgeBaseIndexConfigUpdateResponse> {
  return apiFetch<KnowledgeBaseIndexConfigUpdateResponse>(
    '/api/v1/knowledge-bases/' + kbId + '/index-config',
    {
      method: 'PUT',
      body: JSON.stringify({ index_config }),
    }
  );
}

/**
 * 删除知识库
 */
export async function deleteKnowledgeBase(kbId: string): Promise<void> {
  await apiFetch<void>('/api/v1/knowledge-bases/' + kbId + '?confirm=true', {
    method: 'DELETE',
  });
}

/**
 * 归档知识库
 */
export async function archiveKnowledgeBase(kbId: string): Promise<KnowledgeBase> {
  return apiFetch<KnowledgeBase>('/api/v1/knowledge-bases/' + kbId + '/archive', {
    method: 'POST',
  });
}

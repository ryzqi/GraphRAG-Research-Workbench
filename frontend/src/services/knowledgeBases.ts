/**
 * 知识库 API 封装
 */

import { apiFetch } from './http';
import type { IndexRebuildJob } from './indexRebuilds';
import type { ListResponse } from './types';

export type ChunkingStrategy =
  | 'sliding_window'
  | 'max_min_semantic'
  | 'parent_child'
  | 'markdown_heading';

export interface MarkdownHeadingConfig {
  max_heading_level: number;
  chunk_size: number;
  chunk_overlap: number;
}

export interface SlidingWindowConfig {
  chunk_size: number;
  chunk_overlap: number;
}

export interface SemanticConfig {
  min_tokens: number;
  max_tokens: number;
  similarity_threshold: number;
  overlap_chars: number;
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
  sliding_window: SlidingWindowConfig;
  semantic: SemanticConfig;
  parent_child: ParentChildConfig;
}

export interface ContextualConfig {
  enabled: boolean;
  timeout_seconds: number;
  max_tokens: number;
  concurrency: number;
}

export interface RetrievalParentChildConfig {
  enabled: boolean;
  max_parents: number;
  max_children_per_parent: number;
}

export interface RetrievalConfig {
  parent_child: RetrievalParentChildConfig;
}

export interface IndexConfig {
  chunking: ChunkingConfig;
  contextual: ContextualConfig;
  retrieval: RetrievalConfig;
}

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  tags: string[] | null;
  status: 'active' | 'archived';
  index_config: IndexConfig | null;
  created_at: string;
  updated_at: string;
}

export type KnowledgeBaseListResponse = ListResponse<KnowledgeBase>;
export type KnowledgeBaseStatusFilter = 'active' | 'archived' | 'all';

export interface KnowledgeBaseCreate {
  name: string;
  description?: string;
  tags?: string[];
  index_config?: IndexConfig;
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
        chunk_size: 4000,
        chunk_overlap: 200,
      },
      general_strategy: 'sliding_window',
      sliding_window: {
        chunk_size: 512,
        chunk_overlap: 64,
      },
      semantic: {
        min_tokens: 80,
        max_tokens: 256,
        similarity_threshold: 0.6,
        overlap_chars: 64,
      },
      parent_child: {
        parent: {
          chunk_size: 2000,
          chunk_overlap: 200,
        },
        child: {
          chunk_size: 400,
          chunk_overlap: 50,
        },
      },
    },
    contextual: {
      enabled: true,
      timeout_seconds: 15,
      max_tokens: 128,
      concurrency: 3,
    },
    retrieval: {
      parent_child: {
        enabled: false,
        max_parents: 6,
        max_children_per_parent: 2,
      },
    },
  };
}

/**
 * 获取知识库列表
 */
export async function listKnowledgeBases(params?: {
  status?: KnowledgeBaseStatusFilter;
  skip?: number;
  limit?: number;
}): Promise<KnowledgeBaseListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set('status', params.status);
  if (params?.skip !== undefined) searchParams.set('skip', String(params.skip));
  if (params?.limit !== undefined) searchParams.set('limit', String(params.limit));
  const query = searchParams.toString();
  return apiFetch<KnowledgeBaseListResponse>(
    `/api/v1/knowledge-bases${query ? `?${query}` : ''}`
  );
}

/**
 * 获取知识库详情
 */
export async function getKnowledgeBase(kbId: string): Promise<KnowledgeBase> {
  return apiFetch<KnowledgeBase>(`/api/v1/knowledge-bases/${kbId}`);
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
  return apiFetch<KnowledgeBase>(`/api/v1/knowledge-bases/${kbId}`, {
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
    `/api/v1/knowledge-bases/${kbId}/index-config`,
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
  await apiFetch<void>(`/api/v1/knowledge-bases/${kbId}?confirm=true`, {
    method: 'DELETE',
  });
}

/**
 * 归档知识库
 */
export async function archiveKnowledgeBase(kbId: string): Promise<KnowledgeBase> {
  return apiFetch<KnowledgeBase>(`/api/v1/knowledge-bases/${kbId}/archive`, {
    method: 'POST',
  });
}

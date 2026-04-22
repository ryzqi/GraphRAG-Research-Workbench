/**
 * 知识库 API 封装
 */

import { apiFetch, apiV1Path, type ApiFetchOptions } from './http';
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

export interface IndexConfigNumberConstraint {
  min: number;
  max: number;
}

export interface MarkdownHeadingConfigConstraints {
  max_heading_level: IndexConfigNumberConstraint;
  chunk_size: IndexConfigNumberConstraint;
  chunk_overlap: IndexConfigNumberConstraint;
}

export interface QueryDependentMultiscaleWindowConfigConstraints {
  chunk_size_tokens: IndexConfigNumberConstraint;
  chunk_overlap_tokens: IndexConfigNumberConstraint;
}

export interface QueryDependentMultiscaleConfigConstraints {
  window_count_max: number;
  window: QueryDependentMultiscaleWindowConfigConstraints;
}

export interface SemanticConfigConstraints {
  min_tokens: IndexConfigNumberConstraint;
  max_tokens: IndexConfigNumberConstraint;
  breakpoint_percentile: IndexConfigNumberConstraint;
  similarity_threshold: IndexConfigNumberConstraint;
  overlap_chars: IndexConfigNumberConstraint;
  embedding_batch_size: IndexConfigNumberConstraint;
}

export interface ParentChunkConfigConstraints {
  chunk_size: IndexConfigNumberConstraint;
  chunk_overlap: IndexConfigNumberConstraint;
}

export interface ChildChunkConfigConstraints {
  chunk_size: IndexConfigNumberConstraint;
  chunk_overlap: IndexConfigNumberConstraint;
}

export interface ParentChildConfigConstraints {
  parent: ParentChunkConfigConstraints;
  child: ChildChunkConfigConstraints;
}

export interface ContextualConfigConstraints {
  max_tokens: IndexConfigNumberConstraint;
  concurrency: IndexConfigNumberConstraint;
}

export interface IndexConfigConstraints {
  markdown_heading: MarkdownHeadingConfigConstraints;
  query_dependent_multiscale: QueryDependentMultiscaleConfigConstraints;
  semantic: SemanticConfigConstraints;
  parent_child: ParentChildConfigConstraints;
  contextual: ContextualConfigConstraints;
}

export interface KnowledgeBaseTextLengthConstraint {
  min_length: number | null;
  max_length: number;
}

export interface KnowledgeBaseFormConstraints {
  name: KnowledgeBaseTextLengthConstraint;
  description: KnowledgeBaseTextLengthConstraint;
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
  description?: string | null;
  tags?: string[] | null;
}

export interface KnowledgeBaseIndexConfigUpdateResponse {
  knowledge_base: KnowledgeBase;
  rebuild_job: IndexRebuildJob | null;
}

export function cloneIndexConfig(config: IndexConfig): IndexConfig {
  return {
    chunking: {
      markdown_heading: { ...config.chunking.markdown_heading },
      general_strategy: config.chunking.general_strategy,
      query_dependent_multiscale: {
        windows: config.chunking.query_dependent_multiscale.windows.map((window) => ({ ...window })),
      },
      semantic: { ...config.chunking.semantic },
      parent_child: {
        parent: { ...config.chunking.parent_child.parent },
        child: { ...config.chunking.parent_child.child },
      },
    },
    contextual: { ...config.contextual },
  };
}

export function parseKnowledgeBaseTagsInput(tagsInput: string): string[] {
  return tagsInput
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);
}

export function buildKnowledgeBaseUpdatePayload(input: {
  name: string;
  description: string;
  tagsInput: string;
}): KnowledgeBaseUpdate {
  const tags = parseKnowledgeBaseTagsInput(input.tagsInput);
  const normalizedDescription = input.description.trim();

  return {
    name: input.name.trim(),
    description: normalizedDescription || null,
    tags: tags.length > 0 ? tags : null,
  };
}

export function mergeKnowledgeBaseIntoCollection(
  current: KnowledgeBase[] | undefined,
  updated: KnowledgeBase
): KnowledgeBase[] | undefined {
  if (!current) {
    return current;
  }

  let matched = false;
  const next = current.map((item) => {
    if (item.id !== updated.id) {
      return item;
    }
    matched = true;
    return updated;
  });

  return matched ? next : current;
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
  return apiFetch<KnowledgeBaseListResponse>(apiV1Path(`/knowledge-bases${query ? `?${query}` : ''}`));
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
    apiV1Path(`/knowledge-bases/selectable${query ? `?${query}` : ''}`),
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
  return apiFetch<KnowledgeBase>(apiV1Path(`/knowledge-bases/${kbId}`), options);
}

/**
 * 获取知识库 ingestion 状态
 */
export async function getKnowledgeBaseIngestionState(
  kbId: string,
  options?: ApiFetchOptions
): Promise<KnowledgeBaseIngestionState> {
  return apiFetch<KnowledgeBaseIngestionState>(
    apiV1Path(`/knowledge-bases/${kbId}/ingestion-state`),
    options
  );
}

/**
 * 创建知识库
 */
export async function createKnowledgeBase(
  data: KnowledgeBaseCreate
): Promise<KnowledgeBase> {
  return apiFetch<KnowledgeBase>(apiV1Path('/knowledge-bases'), {
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
  return apiFetch<KnowledgeBase>(apiV1Path(`/knowledge-bases/${kbId}`), {
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
    apiV1Path(`/knowledge-bases/${kbId}/index-config`),
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
  await apiFetch<void>(apiV1Path(`/knowledge-bases/${kbId}?confirm=true`), {
    method: 'DELETE',
  });
}

/**
 * 归档知识库
 */
export async function archiveKnowledgeBase(kbId: string): Promise<KnowledgeBase> {
  return apiFetch<KnowledgeBase>(apiV1Path(`/knowledge-bases/${kbId}/archive`), {
    method: 'POST',
  });
}

/**
 * 知识库 API 封装
 */

import { apiFetch } from './http';

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  tags: string[] | null;
  status: 'active' | 'archived';
  created_at: string;
  updated_at: string;
}

export interface KnowledgeBaseListResponse {
  items: KnowledgeBase[];
}

export interface KnowledgeBaseCreate {
  name: string;
  description?: string;
  tags?: string[];
}

export interface KnowledgeBaseUpdate {
  name?: string;
  description?: string;
  tags?: string[];
}

/**
 * 获取所有活跃知识库列表
 */
export async function listKnowledgeBases(): Promise<KnowledgeBaseListResponse> {
  return apiFetch<KnowledgeBaseListResponse>('/api/v1/knowledge-bases');
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

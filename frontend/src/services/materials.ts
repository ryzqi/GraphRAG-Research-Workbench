/**
 * 资料 API 封装
 */

import { apiFetch, buildAuthHeaders, getApiBaseUrl } from './http';
import type { ListResponse } from './types';

export type SourceType = 'upload' | 'url' | 'text';

export interface SourceMaterial {
  id: string;
  kb_id: string;
  source_type: SourceType;
  title: string;
  uri: string | null;
  mime_type: string | null;
  created_at: string;
  updated_at: string;
}

export type MaterialListResponse = ListResponse<SourceMaterial>;

export interface MaterialCreateText {
  source_type: 'text';
  title: string;
  text: string;
}

export interface MaterialCreateUrl {
  source_type: 'url';
  title: string;
  url: string;
}

/**
 * 获取知识库下的所有资料
 */
export async function listMaterials(kbId: string): Promise<MaterialListResponse> {
  return apiFetch<MaterialListResponse>(`/api/v1/knowledge-bases/${kbId}/materials`);
}

/**
 * 创建文本资料
 */
export async function createTextMaterial(
  kbId: string,
  data: MaterialCreateText
): Promise<SourceMaterial> {
  return apiFetch<SourceMaterial>(`/api/v1/knowledge-bases/${kbId}/materials`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 创建 URL 资料
 */
export async function createUrlMaterial(
  kbId: string,
  data: MaterialCreateUrl
): Promise<SourceMaterial> {
  return apiFetch<SourceMaterial>(`/api/v1/knowledge-bases/${kbId}/materials`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 上传文件资料
 */
export async function uploadMaterial(
  kbId: string,
  title: string,
  file: File
): Promise<SourceMaterial> {
  const formData = new FormData();
  formData.append('title', title);
  formData.append('file', file);

  const requestId = globalThis.crypto?.randomUUID?.() ?? `req_${Date.now()}`;
  const headers = new Headers(buildAuthHeaders());
  headers.set('X-Request-Id', requestId);

  const res = await fetch(`${getApiBaseUrl()}/api/v1/knowledge-bases/${kbId}/materials/upload`, {
    method: 'POST',
    headers,
    body: formData,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.error?.message ?? `上传失败（${res.status}）`);
  }

  return res.json();
}

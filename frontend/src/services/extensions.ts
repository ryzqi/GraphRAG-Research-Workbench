/**
 * 扩展管理 API 封装
 */

import { apiFetch } from './http';
import type { ListResponse } from './types';

export type ExtensionTransport = 'stdio' | 'http';
export type ExtensionStatus = 'enabled' | 'disabled';
export type ExtensionHttpProtocol = 'streamable_http';
export type ExtensionAuthType = 'none' | 'bearer' | 'basic';
export type ExtensionConnectionStatus = 'ok' | 'degraded' | 'failed';

export interface HttpAuthConfig {
  type: ExtensionAuthType;
  token?: string | null;
}

export interface ExtensionHttpConfig {
  url: string;
  protocol: ExtensionHttpProtocol;
  headers: Record<string, string>;
  auth: HttpAuthConfig;
  timeout_seconds?: number | null;
}

export interface ExtensionStdioConfig {
  template_id: string;
  args: string[];
  env: Record<string, string>;
  timeout_seconds?: number | null;
}

export interface ExtensionSecurityConfig {
  allowlist_tools: string[];
  confirmation_required: boolean;
}

export interface ExtensionObservabilityConfig {
  emit_metrics: boolean;
  log_level_override?: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | null;
}

export interface ToolExtension {
  id: string;
  name: string;
  transport: ExtensionTransport;
  status: ExtensionStatus;
  http_config: ExtensionHttpConfig | null;
  stdio_config: ExtensionStdioConfig | null;
  security_config: ExtensionSecurityConfig;
  observability_config: ExtensionObservabilityConfig | null;
  created_at: string;
  updated_at: string;
}

export interface ToolExtensionCreate {
  name: string;
  transport: ExtensionTransport;
  status?: ExtensionStatus;
  http_config?: ExtensionHttpConfig | null;
  stdio_config?: ExtensionStdioConfig | null;
  security_config: ExtensionSecurityConfig;
  observability_config?: ExtensionObservabilityConfig | null;
}

export interface ToolExtensionUpdate {
  name?: string;
  transport?: ExtensionTransport;
  status?: ExtensionStatus;
  http_config?: ExtensionHttpConfig | null;
  stdio_config?: ExtensionStdioConfig | null;
  security_config?: ExtensionSecurityConfig;
  observability_config?: ExtensionObservabilityConfig | null;
}

export interface ToolDescriptor {
  name: string;
  description: string | null;
  input_schema: Record<string, unknown> | null;
}

export interface ToolDescriptorListResponse extends ListResponse<ToolDescriptor> {
  connection_status: ExtensionConnectionStatus;
  last_error: string | null;
  latency_ms: number | null;
}

export interface StdioTemplateDescriptor {
  id: string;
  label: string;
  description: string | null;
  command: string;
  args: string[];
}

export interface StdioTemplateListResponse {
  items: StdioTemplateDescriptor[];
}

export type ToolExtensionListResponse = ListResponse<ToolExtension>;

/**
 * 获取扩展列表
 */
export async function listExtensions(params?: {
  status_filter?: ExtensionStatus;
  skip?: number;
  limit?: number;
}): Promise<ToolExtensionListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.status_filter) searchParams.set('status_filter', params.status_filter);
  if (params?.skip !== undefined) searchParams.set('skip', String(params.skip));
  if (params?.limit !== undefined) searchParams.set('limit', String(params.limit));
  const query = searchParams.toString();
  return apiFetch<ToolExtensionListResponse>(`/api/v1/extensions${query ? `?${query}` : ''}`);
}

/**
 * 获取扩展详情
 */
export async function getExtension(extensionId: string): Promise<ToolExtension> {
  return apiFetch<ToolExtension>(`/api/v1/extensions/${extensionId}`);
}

/**
 * 获取 STDIO 模板列表
 */
export async function listStdioTemplates(): Promise<StdioTemplateListResponse> {
  return apiFetch<StdioTemplateListResponse>('/api/v1/extensions/stdio-templates');
}

/**
 * 创建扩展
 */
export async function createExtension(data: ToolExtensionCreate): Promise<ToolExtension> {
  return apiFetch<ToolExtension>('/api/v1/extensions', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 更新扩展
 */
export async function updateExtension(
  extensionId: string,
  data: ToolExtensionUpdate
): Promise<ToolExtension> {
  return apiFetch<ToolExtension>(`/api/v1/extensions/${extensionId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

/**
 * 删除扩展
 */
export async function deleteExtension(extensionId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/extensions/${extensionId}`, {
    method: 'DELETE',
  });
}

/**
 * 获取扩展工具列表
 */
export async function getExtensionTools(
  extensionId: string,
  params?: { skip?: number; limit?: number }
): Promise<ToolDescriptorListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.skip !== undefined) searchParams.set('skip', String(params.skip));
  if (params?.limit !== undefined) searchParams.set('limit', String(params.limit));
  const query = searchParams.toString();
  return apiFetch<ToolDescriptorListResponse>(
    `/api/v1/extensions/${extensionId}/tools${query ? `?${query}` : ''}`
  );
}

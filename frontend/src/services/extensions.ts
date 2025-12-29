/**
 * 扩展管理 API 封装
 */

import { apiFetch } from './http';

export type ExtensionTransport = 'stdio' | 'http';
export type ExtensionStatus = 'enabled' | 'disabled';
export type InvocationStatus = 'succeeded' | 'failed' | 'canceled';

export interface ToolExtension {
  id: string;
  name: string;
  transport: ExtensionTransport;
  endpoint: string;
  status: ExtensionStatus;
  scope: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface ToolExtensionCreate {
  name: string;
  transport: ExtensionTransport;
  endpoint: string;
  scope?: Record<string, unknown>;
}

export interface ToolExtensionUpdate {
  name?: string;
  transport?: ExtensionTransport;
  endpoint?: string;
  status?: ExtensionStatus;
  scope?: Record<string, unknown>;
}

export interface ToolDescriptor {
  name: string;
  description: string | null;
  input_schema: Record<string, unknown> | null;
}

export interface ToolInvocationSummary {
  tool_name: string;
  purpose: string | null;
  status: InvocationStatus;
  extension_name: string | null;
}

/**
 * 获取扩展列表
 */
export async function listExtensions(status?: ExtensionStatus): Promise<ToolExtension[]> {
  const params = status ? `?status_filter=${status}` : '';
  return apiFetch<ToolExtension[]>(`/api/v1/extensions${params}`);
}

/**
 * 获取扩展详情
 */
export async function getExtension(extensionId: string): Promise<ToolExtension> {
  return apiFetch<ToolExtension>(`/api/v1/extensions/${extensionId}`);
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
export async function getExtensionTools(extensionId: string): Promise<ToolDescriptor[]> {
  return apiFetch<ToolDescriptor[]>(`/api/v1/extensions/${extensionId}/tools`);
}

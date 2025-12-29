/**
 * 研究 API 封装
 */

import { apiFetch } from './http';
import type { AgentMode, AgentRun } from './chats';

export interface ResearchRunCreateRequest {
  question: string;
  selected_kb_ids: string[];
  allow_external?: boolean;
  mode: AgentMode;
}

export interface ResearchReport {
  id: string;
  run_id: string;
  content_md: string;
  citations: Array<Record<string, unknown>>;
  created_at: string;
}

/**
 * 发起深度研究
 */
export async function createResearchRun(data: ResearchRunCreateRequest): Promise<AgentRun> {
  return apiFetch<AgentRun>('/api/v1/research/runs', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 获取研究状态
 */
export async function getResearchRun(runId: string): Promise<AgentRun> {
  return apiFetch<AgentRun>(`/api/v1/research/runs/${runId}`);
}

/**
 * 取消研究任务
 */
export async function cancelResearchRun(runId: string): Promise<AgentRun> {
  return apiFetch<AgentRun>(`/api/v1/research/runs/${runId}/cancel`, {
    method: 'POST',
  });
}

/**
 * 获取研究报告
 */
export async function getResearchReport(runId: string): Promise<ResearchReport> {
  return apiFetch<ResearchReport>(`/api/v1/research/runs/${runId}/report`);
}

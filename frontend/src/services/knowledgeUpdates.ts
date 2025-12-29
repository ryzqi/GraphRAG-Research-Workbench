/**
 * 候选沉淀 API 封装
 */

import { apiFetch } from './http';

export type ProposalStatus = 'pending' | 'approved' | 'rejected' | 'applied';

export interface ProposalCreate {
  kb_id: string;
  source_run_id: string;
  summary: string;
  payload: Record<string, unknown>;
}

export interface ProposalUpdate {
  status?: ProposalStatus;
  reviewed_by?: string;
}

export interface Proposal {
  id: string;
  kb_id: string;
  source_run_id: string | null;
  summary: string;
  payload: Record<string, unknown>;
  status: ProposalStatus;
  created_by: string | null;
  reviewed_by: string | null;
  created_at: string;
  reviewed_at: string | null;
}

/**
 * 创建候选沉淀
 */
export async function createProposal(data: ProposalCreate): Promise<Proposal> {
  return apiFetch<Proposal>('/api/v1/knowledge-updates', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 列出候选沉淀
 */
export async function listProposals(params?: {
  kb_id?: string;
  status?: ProposalStatus;
}): Promise<Proposal[]> {
  const searchParams = new URLSearchParams();
  if (params?.kb_id) searchParams.set('kb_id', params.kb_id);
  if (params?.status) searchParams.set('status', params.status);
  const query = searchParams.toString();
  return apiFetch<Proposal[]>(`/api/v1/knowledge-updates${query ? `?${query}` : ''}`);
}

/**
 * 获取候选沉淀详情
 */
export async function getProposal(proposalId: string): Promise<Proposal> {
  return apiFetch<Proposal>(`/api/v1/knowledge-updates/${proposalId}`);
}

/**
 * 更新候选沉淀状态
 */
export async function updateProposal(
  proposalId: string,
  data: ProposalUpdate
): Promise<Proposal> {
  return apiFetch<Proposal>(`/api/v1/knowledge-updates/${proposalId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

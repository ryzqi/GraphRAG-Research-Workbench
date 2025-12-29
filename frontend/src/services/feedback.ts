/**
 * 反馈 API 封装
 */

import { apiFetch } from './http';

export type FeedbackStatus = 'pending' | 'reviewed' | 'resolved' | 'dismissed';

export interface FeedbackCreate {
  run_id: string;
  rating: number;
  comment?: string;
}

export interface FeedbackUpdate {
  status?: FeedbackStatus;
  resolution_note?: string;
}

export interface Feedback {
  id: string;
  run_id: string;
  rating: number;
  comment: string | null;
  status: FeedbackStatus;
  resolution_note: string | null;
  created_at: string;
  updated_at: string | null;
}

/**
 * 提交反馈
 */
export async function createFeedback(data: FeedbackCreate): Promise<Feedback> {
  return apiFetch<Feedback>('/api/v1/feedback', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 列出反馈
 */
export async function listFeedback(params?: {
  status?: FeedbackStatus;
  run_id?: string;
}): Promise<Feedback[]> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set('status', params.status);
  if (params?.run_id) searchParams.set('run_id', params.run_id);
  const query = searchParams.toString();
  return apiFetch<Feedback[]>(`/api/v1/feedback${query ? `?${query}` : ''}`);
}

/**
 * 获取反馈详情
 */
export async function getFeedback(feedbackId: string): Promise<Feedback> {
  return apiFetch<Feedback>(`/api/v1/feedback/${feedbackId}`);
}

/**
 * 更新反馈状态
 */
export async function updateFeedback(
  feedbackId: string,
  data: FeedbackUpdate
): Promise<Feedback> {
  return apiFetch<Feedback>(`/api/v1/feedback/${feedbackId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

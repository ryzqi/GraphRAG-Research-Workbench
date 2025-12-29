/**
 * 对话 API 封装
 */

import { apiFetch } from './http';

export type ChatSessionType = 'kb_chat' | 'general_chat';
export type AgentMode = 'single_agent' | 'multi_agent';
export type MessageRole = 'user' | 'assistant' | 'system';
export type AgentRunStatus = 'running' | 'succeeded' | 'failed' | 'canceled';
export type EvidenceSourceKind = 'kb' | 'external';

export interface ChatSessionCreate {
  session_type: ChatSessionType;
  selected_kb_ids?: string[];
  allow_external?: boolean;
  mode: AgentMode;
}

export interface ChatSession {
  id: string;
  session_type: ChatSessionType;
  selected_kb_ids: string[] | null;
  allow_external: boolean;
  mode: AgentMode;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  created_at: string;
}

export interface EvidenceItem {
  source_kind: EvidenceSourceKind;
  kb_id: string | null;
  material_id: string | null;
  chunk_id: string | null;
  locator: Record<string, unknown> | null;
  excerpt: string;
}

export interface AgentRun {
  id: string;
  run_type: string;
  status: AgentRunStatus;
  mode: AgentMode;
  question: string;
  selected_kb_ids: string[] | null;
  allow_external: boolean;
  stage_summaries: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

export interface ChatAnswerResponse {
  assistant_message: ChatMessage;
  evidence: EvidenceItem[];
  run: AgentRun;
}

/**
 * 创建会话
 */
export async function createChatSession(data: ChatSessionCreate): Promise<ChatSession> {
  return apiFetch<ChatSession>('/api/v1/chats', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 获取会话详情
 */
export async function getChatSession(sessionId: string): Promise<ChatSession> {
  return apiFetch<ChatSession>(`/api/v1/chats/${sessionId}`);
}

/**
 * 发送消息并获取回答
 */
export async function sendMessage(
  sessionId: string,
  content: string
): Promise<ChatAnswerResponse> {
  return apiFetch<ChatAnswerResponse>(`/api/v1/chats/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

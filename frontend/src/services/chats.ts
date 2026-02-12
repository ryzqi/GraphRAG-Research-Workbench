/**
 * 对话 API 封装
 */

import { apiFetch } from './http';
import { openSseStream } from './sse';
import type { SseEvent } from '../lib/sse';

export type ChatSessionType = 'kb_chat' | 'general_chat';
export type AgentMode = 'single_agent' | 'multi_agent';
export type MessageRole = 'user' | 'assistant' | 'system';
export type AgentRunStatus = 'running' | 'succeeded' | 'failed' | 'canceled';
export type EvidenceSourceKind = 'kb' | 'external';
export type ChatMessageResponseStatus =
  | 'succeeded'
  | 'pending_tool_approval'
  | 'pending_user_clarification';

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

export interface RecentChatSession {
  id: string;
  session_type: ChatSessionType;
  title: string | null;
  updated_at: string;
}

export interface RecentChatListResponse {
  items: RecentChatSession[];
  web_search_available: boolean;
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
  status: 'succeeded';
  assistant_message: ChatMessage;
  evidence: EvidenceItem[];
  run: AgentRun;
}

export interface PendingToolCall {
  extension_id: string;
  extension_name: string | null;
  tool_name: string;
  args: Record<string, unknown>;
  is_builtin: boolean;
}

export interface ChatPendingToolApprovalResponse {
  status: 'pending_tool_approval';
  thread_id: string;
  interrupt_id: string | null;
  message: string | null;
  pending_tool_calls: PendingToolCall[];
  run: AgentRun;
}

export interface ChatPendingUserClarificationResponse {
  status: 'pending_user_clarification';
  thread_id: string;
  message: string;
  run: AgentRun;
}

export type ChatMessageResponse =
  | ChatAnswerResponse
  | ChatPendingToolApprovalResponse
  | ChatPendingUserClarificationResponse;

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
 * 删除会话
 */
export async function deleteChatSession(sessionId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/chats/${sessionId}`, {
    method: 'DELETE',
  });
}

/**
 * 获取最近对话
 */
export async function getRecentChats(limit = 20): Promise<RecentChatListResponse> {
  return apiFetch<RecentChatListResponse>(`/api/v1/chats/recent?limit=${limit}`);
}

/**
 * 获取会话消息
 */
export async function getChatMessages(sessionId: string): Promise<ChatMessage[]> {
  return apiFetch<ChatMessage[]>(`/api/v1/chats/${sessionId}/messages`);
}

/**
 * 发送消息并获取回答
 */
export async function sendMessage(
  sessionId: string,
  content: string
): Promise<ChatMessageResponse> {
  return apiFetch<ChatMessageResponse>(`/api/v1/chats/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

/**
 * 两阶段交互：提交工具审批并恢复执行
 */
export async function resumeToolApproval(
  sessionId: string,
  runId: string,
  approved: boolean
): Promise<ChatMessageResponse> {
  return apiFetch<ChatMessageResponse>(`/api/v1/chats/${sessionId}/runs/${runId}/resume`, {
    method: 'POST',
    body: JSON.stringify({ approved }),
  });
}

/**
 * 发送消息并获取流式回答
 */
export async function streamChatMessage(
  sessionId: string,
  content: string,
  signal?: AbortSignal
): Promise<AsyncIterable<SseEvent>> {
  return openSseStream(
    `/api/v1/chats/${sessionId}/messages/stream`,
    {
      method: 'POST',
      body: JSON.stringify({ content }),
    },
    signal
  );
}

/**
 * 两阶段交互：提交工具审批并恢复执行（流式）
 */
export async function streamResumeToolApproval(
  sessionId: string,
  runId: string,
  approved: boolean,
  signal?: AbortSignal
): Promise<AsyncIterable<SseEvent>> {
  return openSseStream(
    `/api/v1/chats/${sessionId}/runs/${runId}/resume/stream`,
    {
      method: 'POST',
      body: JSON.stringify({ approved }),
    },
    signal
  );
}

/**
 * 提交澄清信息并恢复 KB Chat 执行
 */
export async function resumeClarification(
  sessionId: string,
  runId: string,
  content: string
): Promise<ChatMessageResponse> {
  return apiFetch<ChatMessageResponse>(`/api/v1/chats/${sessionId}/runs/${runId}/clarification`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

/**
 * 提交澄清信息并恢复 KB Chat 执行（流式）
 */
export async function streamResumeClarification(
  sessionId: string,
  runId: string,
  content: string,
  signal?: AbortSignal
): Promise<AsyncIterable<SseEvent>> {
  return openSseStream(
    `/api/v1/chats/${sessionId}/runs/${runId}/clarification/stream`,
    {
      method: 'POST',
      body: JSON.stringify({ content }),
    },
    signal
  );
}

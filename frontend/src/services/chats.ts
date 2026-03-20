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
export type ChatRunStreamStatus = AgentRunStatus | 'waiting_user';
export type TerminalRunStatus = Exclude<ChatRunStreamStatus, 'running'>;
export type EvidenceSourceKind = 'kb' | 'external';
export type ChatMessageResponseStatus =
  | 'succeeded'
  | 'pending_tool_approval'
  | 'pending_user_clarification';

const CHAT_RUN_STREAM_STATUS_VALUES = [
  'running',
  'succeeded',
  'failed',
  'canceled',
  'waiting_user',
] as const;

export interface ChatRunProgress {
  completed: number;
  total: number;
  percent: number;
}

export interface ChatRunStateEvent {
  run_id: string;
  run_status: ChatRunStreamStatus;
  current_step_id: string | null;
  current_step_label: string | null;
  current_step_status: string | null;
  current_node: string | null;
  attempt: number | null;
  message: string | null;
  state_version?: number;
  active_path?: string[];
  last_good_answer?: string | null;
  degrade_reason?: string | null;
  progress: ChatRunProgress;
  ts: string;
}

export interface ChatRunUiEvent {
  event_type: string;
  run_id: string;
  step_id?: string | null;
  status?: string | null;
  node?: string | null;
  message?: string | null;
  candidate_answer?: string | null;
  source_step_id?: string | null;
  degrade_reason?: string | null;
  meta?: Record<string, unknown> | null;
  ts: string;
}

export type ChatTraceExecutionStatus =
  | 'started'
  | 'completed'
  | 'failed'
  | 'waiting_user'
  | 'skipped';

export interface KbChatConfig {
  retrieval_top_k: number;
  retrieval_rerank_top_k: number;
  retrieval_hybrid_rrf_k: number;
  retrieval_parent_max_parents: number;
  retrieval_parent_max_children_per_parent: number;
  retrieval_multiscale_per_window_top_k: number;
  retrieval_multiscale_rrf_k: number;
  retrieval_multiscale_max_documents: number;
  retrieval_multiscale_max_chunks_per_document: number;
}

export interface ChatSessionCreate {
  session_type: ChatSessionType;
  selected_kb_ids?: string[];
  allow_external?: boolean;
  mode: AgentMode;
  kb_chat_config?: KbChatConfig;
}

export interface ChatSession {
  id: string;
  session_type: ChatSessionType;
  selected_kb_ids: string[] | null;
  allow_external: boolean;
  mode: AgentMode;
  kb_chat_config: KbChatConfig | null;
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
  citation_id?: string | null;
  citation_title?: string | null;
  citation_page_hint?: string | null;
  citation_source?: string | null;
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
  source?: 'live' | 'cached';
  cache?: SemanticCacheMeta | null;
  stage_summaries?: Record<string, unknown> | null;
  metrics?: Record<string, unknown> | null;
  run: AgentRun;
}

export interface SemanticCacheMeta {
  hit: boolean;
  score?: number | null;
  threshold?: number | null;
  ttl_seconds?: number | null;
}

export interface PendingToolCall {
  extension_id: string;
  extension_name: string | null;
  tool_name: string;
  args: Record<string, unknown>;
  is_builtin: boolean;
}

export interface PendingInterruptApproval {
  interrupt_id: string;
  message: string | null;
  pending_tool_calls: PendingToolCall[];
}

export interface ToolDecision {
  type: 'approve' | 'reject' | 'edit';
  message?: string;
  edited_action?: Record<string, unknown>;
}

export interface InterruptDecisionBatch {
  interrupt_id: string;
  decisions: ToolDecision[];
}

export interface ToolApprovalRequest {
  interrupts: InterruptDecisionBatch[];
}

export interface ChatPendingToolApprovalResponse {
  status: 'pending_tool_approval';
  thread_id: string;
  pending_interrupts: PendingInterruptApproval[];
  run: AgentRun;
}

export type ClarificationReasonCode =
  | 'missing_entity'
  | 'missing_scope'
  | 'missing_time'
  | 'missing_metric'
  | 'coref_uncertain'
  | 'mixed';

export interface ClarificationSlot {
  key: string;
  label: string;
  required: boolean;
  options: string[];
}

export interface PendingClarification {
  question: string;
  reason_code: ClarificationReasonCode;
  confidence: number;
  model_reason?: string | null;
  slots: ClarificationSlot[];
  suggested_answers: string[];
}

export interface ChatPendingUserClarificationResponse {
  status: 'pending_user_clarification';
  thread_id: string;
  message: string;
  pending_clarification?: PendingClarification | null;
  assistant_message?: ChatMessage | null;
  evidence?: EvidenceItem[] | null;
  source?: 'live' | 'cached';
  cache?: SemanticCacheMeta | null;
  stage_summaries?: Record<string, unknown> | null;
  metrics?: Record<string, unknown> | null;
  run: AgentRun;
}

export type ChatMessageResponse =
  | ChatAnswerResponse
  | ChatPendingToolApprovalResponse
  | ChatPendingUserClarificationResponse;

export type ChatStreamEventName =
  | 'meta'
  | 'heartbeat'
  | 'messages'
  | 'updates'
  | 'custom'
  | 'step'
  | 'state'
  | 'ui_event'
  | 'node_io'
  | 'node_trace'
  | 'tool_trace'
  | 'stream_end'
  | 'interrupt'
  | 'final'
  | 'error';

export const KB_CHAT_CUSTOM_EVENT_TYPES = [
  'node_io',
  'answer_review_subcheck',
  'answer_review_fused',
  'guardrail_warning',
  'heartbeat',
] as const;

export type KbChatCustomEventType = (typeof KB_CHAT_CUSTOM_EVENT_TYPES)[number];

export interface NormalizedChatStreamEvent {
  event: ChatStreamEventName;
  version: string;
  payload: Record<string, unknown>;
}

export interface ChatNodeIoEvent {
  execution_id?: string | null;
  display_input_items?: ChatNodeDisplayItem[] | null;
  display_output_items?: ChatNodeDisplayItem[] | null;
  run_id: string;
  node_name: string;
  node_id: string;
  node_path?: string[] | null;
  phase: 'start' | 'end' | 'error';
  attempt?: number | null;
  latency_ms?: number | null;
  input_summary?: Record<string, unknown> | null;
  output_summary?: Record<string, unknown> | null;
  input_snapshot_meta?: Record<string, unknown> | null;
  output_snapshot_meta?: Record<string, unknown> | null;
  input_snapshot?: Record<string, unknown> | null;
  output_snapshot?: Record<string, unknown> | null;
  error_summary?: string | null;
  ts: string;
}

export interface ChatNodeDisplayItem {
  key: string;
  label: string;
  value: string | string[];
}

export interface ChatTraceExecution {
  execution_id: string;
  run_id?: string;
  node_name: string;
  node_label: string;
  status: ChatTraceExecutionStatus;
  started_at: string;
  updated_at: string;
  ended_at?: string | null;
  node_path?: string[] | null;
  attempt?: number | null;
  latency_ms?: number | null;
  input_items?: ChatNodeDisplayItem[] | null;
  output_items?: ChatNodeDisplayItem[] | null;
  error_summary?: string | null;
}

export interface KbGraphNode {
  id: string;
  label: string;
  phase: string | null;
  order: number | null;
  metadata?: Record<string, unknown>;
}

export interface KbGraphEdge {
  source: string;
  target: string;
  conditional: boolean;
}

export interface KbGraphSchema {
  version: string;
  hash: string;
  nodes: readonly KbGraphNode[];
  edges: readonly KbGraphEdge[];
}

export function isChatRunStreamStatus(value: unknown): value is ChatRunStreamStatus {
  return (
    typeof value === 'string' &&
    (CHAT_RUN_STREAM_STATUS_VALUES as readonly string[]).includes(value)
  );
}

export function resolveTerminalRunStatus(
  status: AgentRunStatus | ChatRunStreamStatus | undefined,
  fallback: TerminalRunStatus = 'failed'
): TerminalRunStatus {
  if (!isChatRunStreamStatus(status)) {
    return fallback;
  }
  if (status === 'running') {
    return fallback;
  }
  return status;
}

export function isUnexpectedStreamEnd(params: {
  sawFinalEvent: boolean;
  sawErrorEvent: boolean;
}): boolean {
  return !params.sawFinalEvent && !params.sawErrorEvent;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function normalizeChatStreamEvent(event: SseEvent): NormalizedChatStreamEvent | null {
  const parsed = (() => {
    try {
      return JSON.parse(event.data) as unknown;
    } catch {
      return null;
    }
  })();
  const record = asRecord(parsed);
  if (!record) {
    return null;
  }

  const explicitType = typeof record.type === 'string' ? record.type : null;
  const normalizedEvent = (explicitType ?? event.event) as ChatStreamEventName;
  const version =
    typeof record.version === 'string'
      ? record.version
      : '2.0';

  return {
    event: normalizedEvent,
    version,
    payload: { ...record },
  };
}

export function toKbGraphSchemaQuery(config: Partial<KbChatConfig>): string {
  const params = new URLSearchParams();
  const orderedKeys: Array<keyof KbChatConfig> = [
    'retrieval_top_k',
    'retrieval_rerank_top_k',
    'retrieval_hybrid_rrf_k',
    'retrieval_parent_max_parents',
    'retrieval_parent_max_children_per_parent',
    'retrieval_multiscale_per_window_top_k',
    'retrieval_multiscale_rrf_k',
    'retrieval_multiscale_max_documents',
    'retrieval_multiscale_max_chunks_per_document',
  ];
  for (const key of orderedKeys) {
    const value = config[key];
    if (typeof value === 'boolean' || typeof value === 'number' || typeof value === 'string') {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return query ? `?${query}` : '';
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
export async function getChatSession(sessionId: string, signal?: AbortSignal): Promise<ChatSession> {
  return apiFetch<ChatSession>(`/api/v1/chats/${sessionId}`, { signal });
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
export async function getChatMessages(
  sessionId: string,
  signal?: AbortSignal
): Promise<ChatMessage[]> {
  return apiFetch<ChatMessage[]>(`/api/v1/chats/${sessionId}/messages`, { signal });
}

export async function getKbChatGraphSchema(
  config: Partial<KbChatConfig> = {}
): Promise<KbGraphSchema> {
  return apiFetch<KbGraphSchema>(
    `/api/v1/chats/kb-graph-schema${toKbGraphSchemaQuery(config)}`
  );
}

/**
 * 发送消息并获取回答
 */
export async function sendMessage(
  sessionId: string,
  content: string,
  clientRequestId?: string
): Promise<ChatMessageResponse> {
  return apiFetch<ChatMessageResponse>(`/api/v1/chats/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({
      content,
      client_request_id: clientRequestId,
    }),
  });
}

/**
 * 两阶段交互：提交工具审批并恢复执行
 */
export async function resumeToolApproval(
  sessionId: string,
  runId: string,
  approval: ToolApprovalRequest
): Promise<ChatMessageResponse> {
  return apiFetch<ChatMessageResponse>(`/api/v1/chats/${sessionId}/runs/${runId}/resume`, {
    method: 'POST',
    body: JSON.stringify(approval),
  });
}

/**
 * 发送消息并获取流式回答
 */
export async function streamChatMessage(
  sessionId: string,
  content: string,
  clientRequestId?: string,
  signal?: AbortSignal
): Promise<AsyncIterable<SseEvent>> {
  return openSseStream(
    `/api/v1/chats/${sessionId}/messages/stream`,
    {
      method: 'POST',
      body: JSON.stringify({
        content,
        client_request_id: clientRequestId,
      }),
    },
    signal
  );
}

export async function getPendingGeneralRun(
  sessionId: string,
  signal?: AbortSignal
): Promise<ChatPendingToolApprovalResponse | null> {
  return apiFetch<ChatPendingToolApprovalResponse | null>(
    `/api/v1/chats/${sessionId}/runs/pending-general`,
    { signal }
  );
}

/**
 * 两阶段交互：提交工具审批并恢复执行（流式）
 */
export async function streamResumeToolApproval(
  sessionId: string,
  runId: string,
  approval: ToolApprovalRequest,
  signal?: AbortSignal
): Promise<AsyncIterable<SseEvent>> {
  return openSseStream(
    `/api/v1/chats/${sessionId}/runs/${runId}/resume/stream`,
    {
      method: 'POST',
      body: JSON.stringify(approval),
    },
    signal
  );
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

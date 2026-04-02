/**
 * 研究 API 封装
 */

import { apiFetch } from './http';
import { openSseStream } from './sse';
import type { SseEvent } from '../lib/sse';
import type {
  ResearchArtifactsResponse,
  ResearchClarificationSubmitRequest,
  ResearchPlanUpdateRequest,
  ResearchSessionAccepted,
  ResearchSessionCreateRequest,
  ResearchStopRequest,
} from '../types/researchEvents';

// Deep Research 的预规划接口会等待 scoper 判定，并停在澄清/计划确认阶段；
// 30 秒默认超时过短，用户在提交补充信息或更新计划后容易被前端提前中断。
const RESEARCH_PLANNING_TIMEOUT_MS = 300_000;

export type {
  ResearchArtifactRead,
  ResearchArtifactsResponse,
  ResearchCanonicalCitation,
  ResearchClarificationQuestion,
  ResearchClarificationRequest,
  ResearchClarificationSubmitRequest,
  ResearchEventEnvelope,
  ResearchPlanUpdateRequest,
  ResearchPlanSnapshot,
  ResearchPlanSubtask,
  ResearchSessionAccepted,
  ResearchSessionCreateRequest,
  ResearchSessionStatus,
  ResearchSessionView,
  ResearchStopRequest,
  ResearchSourceTarget,
  ResearchSourceType,
} from '../types/researchEvents';

export interface ResearchStreamOptions {
  signal?: AbortSignal;
  lastEventId?: string | null;
  resumeFromEventId?: string | null;
}

export function buildResearchStreamPath(
  sessionId: string,
  resumeFromEventId?: string | null
): string {
  const path = `/api/v1/research/sessions/${sessionId}/stream`;
  if (!resumeFromEventId) {
    return path;
  }

  const params = new URLSearchParams({
    resume_from_event_id: resumeFromEventId,
  });
  return `${path}?${params.toString()}`;
}

/**
 * 发起深度研究会话
 */
export async function createResearchSession(
  data: ResearchSessionCreateRequest
): Promise<ResearchSessionAccepted> {
  const payload: ResearchSessionCreateRequest = {
    question: data.question.trim(),
    plan_first: true,
  };

  return apiFetch<ResearchSessionAccepted>('/api/v1/research/sessions', {
    method: 'POST',
    body: JSON.stringify(payload),
    timeoutMs: RESEARCH_PLANNING_TIMEOUT_MS,
  });
}

/**
 * 提交澄清回答
 */
export async function submitResearchClarification(
  sessionId: string,
  data: ResearchClarificationSubmitRequest
): Promise<ResearchSessionAccepted> {
  return apiFetch<ResearchSessionAccepted>(
    `/api/v1/research/sessions/${sessionId}/clarification`,
    {
      method: 'POST',
      body: JSON.stringify(data),
      timeoutMs: RESEARCH_PLANNING_TIMEOUT_MS,
    }
  );
}

export async function updateResearchPlan(
  sessionId: string,
  data: ResearchPlanUpdateRequest
): Promise<ResearchSessionAccepted> {
  return apiFetch<ResearchSessionAccepted>(`/api/v1/research/sessions/${sessionId}/plan`, {
    method: 'POST',
    body: JSON.stringify(data),
    timeoutMs: RESEARCH_PLANNING_TIMEOUT_MS,
  });
}

export async function startResearchSession(sessionId: string): Promise<ResearchSessionAccepted> {
  return apiFetch<ResearchSessionAccepted>(`/api/v1/research/sessions/${sessionId}/start`, {
    method: 'POST',
  });
}

/**
 * 获取研究工件
 */
export async function getResearchArtifacts(
  sessionId: string
): Promise<ResearchArtifactsResponse> {
  return apiFetch<ResearchArtifactsResponse>(
    `/api/v1/research/sessions/${sessionId}/artifacts`
  );
}

/**
 * 中断研究会话
 */
export async function stopResearchSession(
  sessionId: string,
  data: ResearchStopRequest = {}
): Promise<ResearchSessionAccepted> {
  return apiFetch<ResearchSessionAccepted>(`/api/v1/research/sessions/${sessionId}/stop`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 研究事件流
 */
export async function streamResearchSession(
  sessionId: string,
  options: ResearchStreamOptions = {}
): Promise<AsyncIterable<SseEvent>> {
  const headers: Record<string, string> = {};
  if (options.lastEventId) {
    headers['Last-Event-ID'] = options.lastEventId;
  }

  return openSseStream(
    buildResearchStreamPath(sessionId, options.resumeFromEventId),
    {
      method: 'GET',
      ...(Object.keys(headers).length > 0 ? { headers } : {}),
    },
    options.signal
  );
}

/**
 * 研究 API 封装
 */

import { apiFetch } from './http';
import { openSseStream } from './sse';
import type { SseEvent } from '../lib/sse';
import type {
  ResearchArtifactsResponse,
  ResearchInterruptRequest,
  ResearchPlanConfirmRequest,
  ResearchResumeAccepted,
  ResearchResumeRequest,
  ResearchSessionAccepted,
  ResearchSessionCreateRequest,
} from '../types/researchEvents';

export type {
  ResearchArtifactRead,
  ResearchArtifactsResponse,
  ResearchCanonicalCitation,
  ResearchClarificationQuestion,
  ResearchClarificationRequest,
  ResearchEventEnvelope,
  ResearchInterruptRequest,
  ResearchPlanConfirmRequest,
  ResearchPlanSnapshot,
  ResearchPlanSubtask,
  ResearchResumeAccepted,
  ResearchResumeRequest,
  ResearchSessionAccepted,
  ResearchSessionCreateRequest,
  ResearchSessionStatus,
  ResearchSessionView,
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
  });
}

/**
 * 确认研究计划
 */
export async function confirmResearchPlan(
  sessionId: string,
  data: ResearchPlanConfirmRequest
): Promise<ResearchSessionAccepted> {
  return apiFetch<ResearchSessionAccepted>(
    `/api/v1/research/sessions/${sessionId}/confirm-plan`,
    {
      method: 'POST',
      body: JSON.stringify(data),
    }
  );
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
export async function interruptResearchSession(
  sessionId: string,
  data: ResearchInterruptRequest = {}
): Promise<ResearchSessionAccepted> {
  return apiFetch<ResearchSessionAccepted>(
    `/api/v1/research/sessions/${sessionId}/interrupt`,
    {
      method: 'POST',
      body: JSON.stringify(data),
    }
  );
}

/**
 * 恢复研究会话
 */
export async function resumeResearchSession(
  sessionId: string,
  data: ResearchResumeRequest
): Promise<ResearchResumeAccepted> {
  return apiFetch<ResearchResumeAccepted>(
    `/api/v1/research/sessions/${sessionId}/resume`,
    {
      method: 'POST',
      body: JSON.stringify(data),
    }
  );
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

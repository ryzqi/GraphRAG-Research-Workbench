import type { ResearchSessionCreateRequest } from '../services/research';

export interface ResearchStartDraft {
  question: string;
  requireConfirmation?: boolean;
}

export function validateResearchStartDraft(params: {
  question: string;
}): string | null {
  const question = params.question.trim();
  if (!question) {
    return '请输入研究问题';
  }
  return null;
}

export function buildResearchStartRequest(
  draft: ResearchStartDraft
): ResearchSessionCreateRequest {
  return {
    question: draft.question.trim(),
    plan_first: true,
  };
}

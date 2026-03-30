import type { ResearchSessionCreateRequest } from '../services/research';

export interface ResearchStartDraft {
  question: string;
  selectedKbIds: string[];
  allowExternal: boolean;
  requireConfirmation: boolean;
}

export function validateResearchStartDraft(params: {
  question: string;
  selectedKbIds: string[];
  allowExternal: boolean;
}): string | null {
  const question = params.question.trim();
  if (!question) {
    return '请输入研究问题';
  }
  if (params.selectedKbIds.length === 0 && !params.allowExternal) {
    return '请至少选择一个知识库，或开启外部研究';
  }
  return null;
}

export function buildResearchStartRequest(
  draft: ResearchStartDraft
): ResearchSessionCreateRequest {
  return {
    question: draft.question.trim(),
    ...(draft.selectedKbIds.length > 0 ? { selected_kb_ids: [...draft.selectedKbIds] } : {}),
    allow_external: draft.allowExternal,
    require_confirmation: draft.requireConfirmation,
  };
}

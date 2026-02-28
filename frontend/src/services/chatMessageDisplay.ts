export type ConfidenceLevel = 'high' | 'medium' | 'low' | null | undefined;
export type ConfidenceChipColor = 'success' | 'warning' | 'default';

export interface ConfidenceChipMeta {
  color: ConfidenceChipColor;
  label: string;
}

export function resolveConfidenceChipMeta(level: ConfidenceLevel): ConfidenceChipMeta | null {
  if (level === 'high') {
    return { color: 'success', label: '高置信度' };
  }
  if (level === 'medium') {
    return { color: 'warning', label: '中置信度' };
  }
  if (level === 'low') {
    return { color: 'default', label: '低置信度' };
  }
  return null;
}

export function shouldRenderClarificationCard(params: {
  pendingClarification: unknown;
  runId: string | null | undefined;
  hasSubmitHandler: boolean;
}): boolean {
  return Boolean(
    params.pendingClarification &&
      params.runId &&
      params.runId.trim().length > 0 &&
      params.hasSubmitHandler
  );
}

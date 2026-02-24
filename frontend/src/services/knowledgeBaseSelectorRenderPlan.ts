interface KnowledgeBaseSelectorRenderPlanInput {
  currentVisibleCount: number;
  totalCount: number;
  previousDatasetKey: string;
  nextDatasetKey: string;
  initialSize?: number;
}

export function createKnowledgeBaseVisibleCount(totalCount: number, initialSize = 24): number {
  return Math.min(totalCount, Math.max(1, initialSize));
}

export function extendKnowledgeBaseVisibleCount(
  currentVisibleCount: number,
  totalCount: number,
  step = 24
): number {
  return Math.min(totalCount, currentVisibleCount + Math.max(1, step));
}

export function syncKnowledgeBaseVisibleCount(
  input: KnowledgeBaseSelectorRenderPlanInput
): number {
  const { currentVisibleCount, totalCount, previousDatasetKey, nextDatasetKey, initialSize = 24 } = input;
  if (nextDatasetKey !== previousDatasetKey) {
    return createKnowledgeBaseVisibleCount(totalCount, initialSize);
  }
  return Math.min(totalCount, currentVisibleCount);
}

import { describe, expect, it } from 'vitest';

import {
  createKnowledgeBaseVisibleCount,
  extendKnowledgeBaseVisibleCount,
  syncKnowledgeBaseVisibleCount,
} from './knowledgeBaseSelectorRenderPlan';

describe('knowledgeBaseSelectorRenderPlan', () => {
  it('creates bounded initial visible count', () => {
    expect(createKnowledgeBaseVisibleCount(10, 24)).toBe(10);
    expect(createKnowledgeBaseVisibleCount(80, 24)).toBe(24);
  });

  it('extends visible count by chunk', () => {
    expect(extendKnowledgeBaseVisibleCount(24, 80, 24)).toBe(48);
    expect(extendKnowledgeBaseVisibleCount(72, 80, 24)).toBe(80);
  });

  it('resets visible window when dataset changes (filter/switch)', () => {
    expect(
      syncKnowledgeBaseVisibleCount({
        currentVisibleCount: 72,
        totalCount: 120,
        previousDatasetKey: 'all',
        nextDatasetKey: 'filtered:finance',
        initialSize: 24,
      })
    ).toBe(24);
  });
});

import { describe, expect, it } from 'vitest';

import {
  resolveConfidenceChipMeta,
  shouldRenderClarificationCard,
} from './chatMessageDisplay';

describe('chatMessageDisplay', () => {
  it('maps confidence levels to badge label and tone', () => {
    expect(resolveConfidenceChipMeta('high')).toEqual({ color: 'success', label: '高置信度' });
    expect(resolveConfidenceChipMeta('medium')).toEqual({ color: 'warning', label: '中置信度' });
    expect(resolveConfidenceChipMeta('low')).toEqual({ color: 'default', label: '低置信度' });
  });

  it('returns null for unknown confidence level', () => {
    expect(resolveConfidenceChipMeta(null)).toBeNull();
    expect(resolveConfidenceChipMeta(undefined)).toBeNull();
  });

  it('only renders clarification card when pending payload, run id and submit handler all exist', () => {
    expect(
      shouldRenderClarificationCard({
        pendingClarification: { message: '请补充范围' },
        runId: 'run-1',
        hasSubmitHandler: true,
      })
    ).toBe(true);

    expect(
      shouldRenderClarificationCard({
        pendingClarification: null,
        runId: 'run-1',
        hasSubmitHandler: true,
      })
    ).toBe(false);
    expect(
      shouldRenderClarificationCard({
        pendingClarification: { message: 'x' },
        runId: '',
        hasSubmitHandler: true,
      })
    ).toBe(false);
    expect(
      shouldRenderClarificationCard({
        pendingClarification: { message: 'x' },
        runId: 'run-1',
        hasSubmitHandler: false,
      })
    ).toBe(false);
  });
});

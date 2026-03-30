import { describe, expect, it } from 'vitest';

import {
  buildResearchStartRequest,
  type ResearchStartDraft,
  validateResearchStartDraft,
} from './researchPageState';

describe('researchPageState', () => {
  it('allows non-empty research questions', () => {
    expect(
      validateResearchStartDraft({
        question: '比较三种网页研究路线',
      })
    ).toBeNull();
  });

  it('builds a plan-first request payload', () => {
    expect(
      buildResearchStartRequest({
        question: ' 研究问题 ',
      })
    ).toEqual({
      question: '研究问题',
      plan_first: true,
    });
  });

  it('does not keep the legacy requireConfirmation draft field', () => {
    const draft: ResearchStartDraft = {
      question: '研究问题',
      // @ts-expect-error Task 3 removes the legacy toggle contract
      requireConfirmation: true,
    };

    expect(draft.question).toBe('研究问题');
  });

  it('rejects empty questions after trimming whitespace', () => {
    expect(
      validateResearchStartDraft({
        question: '   ',
      })
    ).toBe('请输入研究问题');
  });
});

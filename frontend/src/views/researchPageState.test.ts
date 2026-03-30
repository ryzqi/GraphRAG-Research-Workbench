import { describe, expect, it } from 'vitest';

import {
  buildResearchStartRequest,
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

  it.each([true, false])(
    'builds a plan-first request payload regardless of requireConfirmation=%s',
    (requireConfirmation) => {
      expect(
        buildResearchStartRequest({
          question: ' 研究问题 ',
          requireConfirmation,
        })
      ).toEqual({
        question: '研究问题',
        plan_first: true,
      });
    }
  );

  it('builds a plan-first request payload when no legacy draft flag is provided', () => {
    expect(
      buildResearchStartRequest({
        question: ' 另一条研究问题 ',
      })
    ).toEqual({
      question: '另一条研究问题',
      plan_first: true,
    });
  });

  it('rejects empty questions after trimming whitespace', () => {
    expect(
      validateResearchStartDraft({
        question: '   ',
      })
    ).toBe('请输入研究问题');
  });
});

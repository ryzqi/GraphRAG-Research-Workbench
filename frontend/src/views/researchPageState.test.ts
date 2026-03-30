import { describe, expect, it } from 'vitest';

import {
  buildResearchStartRequest,
  validateResearchStartDraft,
} from './researchPageState';

describe('researchPageState', () => {
  it('allows external-only research without selected KBs', () => {
    expect(
      validateResearchStartDraft({
        question: '比较三种网页研究路线',
        selectedKbIds: [],
        allowExternal: true,
      })
    ).toBeNull();
  });

  it('rejects requests without KBs and without external research', () => {
    expect(
      validateResearchStartDraft({
        question: '无效请求',
        selectedKbIds: [],
        allowExternal: false,
      })
    ).toBe('请至少选择一个知识库，或开启外部研究');
  });

  it('builds request payload from the research page draft', () => {
    expect(
      buildResearchStartRequest({
        question: ' 研究问题 ',
        selectedKbIds: ['kb-1'],
        allowExternal: true,
        requireConfirmation: true,
      })
    ).toEqual({
      question: '研究问题',
      selected_kb_ids: ['kb-1'],
      allow_external: true,
      require_confirmation: true,
    });
  });
});

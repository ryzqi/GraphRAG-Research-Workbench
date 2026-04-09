import { describe, expect, it } from 'vitest';

import { buildResearchSessionView } from './researchEvents';

describe('buildResearchSessionView', () => {
  it('preserves question from accepted session payload', () => {
    const view = buildResearchSessionView({
      accepted: {
        session_id: 'session-1',
        question: '全球人工智能半导体行业：2024年深度分析报告',
        status: 'plan_ready',
        plan_snapshot: null,
        clarification_request: null,
      },
      events: [],
      artifacts: [],
    });

    expect(view.question).toBe('全球人工智能半导体行业：2024年深度分析报告');
  });
});

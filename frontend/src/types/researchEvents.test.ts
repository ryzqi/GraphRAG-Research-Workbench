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
      artifactsStatus: 'plan_ready',
      artifacts: [],
    });

    expect(view.question).toBe('全球人工智能半导体行业：2024年深度分析报告');
  });

  it('uses backend artifacts status instead of inferring final from report artifacts', () => {
    const view = buildResearchSessionView({
      accepted: {
        session_id: 'session-1',
        question: '当前 RAG 领域的最新进展',
        status: 'running',
        plan_snapshot: null,
        clarification_request: null,
      },
      events: [],
      artifactsStatus: 'finalizing',
      artifacts: [
        {
          artifact_key: 'report_md',
          content_text: '# Research Report',
          content_json: null,
          citations: [],
        },
        {
          artifact_key: 'report_json',
          content_text: null,
          content_json: { summary: 'summary' },
          citations: [],
        },
      ],
    });

    expect(view.status).toBe('finalizing');
    const viewRecord = view as unknown as Record<string, unknown>;
    expect(viewRecord.report_md).toBeUndefined();
    expect(viewRecord.report_json).toBeUndefined();
  });
});

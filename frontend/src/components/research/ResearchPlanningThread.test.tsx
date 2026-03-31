import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchPlanningThread } from './ResearchPlanningThread';

describe('ResearchPlanningThread', () => {
  it('renders clarification questions first and hides the confirmation CTA while clarifying', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchPlanningThread, {
        question: '帮我研究适合 20 人团队的 MCP 部署方案',
        status: 'clarifying',
        clarificationRequest: {
          summary: '在开始规划前，还需要补充一点上下文。',
          questions: [
            {
              id: 'audience',
              question: '你更关注内部研发团队，还是对外客户交付？',
              why_it_matters: '受众不同，会影响部署复杂度、权限模型和评估重点。',
            },
          ],
        },
        clarificationDraft: '面向内部研发团队，输出选型建议。',
        onClarificationDraftChange: () => undefined,
        onSubmitClarification: () => undefined,
      })
    );

    expect(html).toContain('帮我研究适合 20 人团队的 MCP 部署方案');
    expect(html).toContain('你更关注内部研发团队，还是对外客户交付？');
    expect(html).toContain('受众不同，会影响部署复杂度、权限模型和评估重点。');
    expect(html).toContain('补充你的回答');
    expect(html).toContain('提交补充信息');
    expect(html).not.toContain('计划草案');
  });
});

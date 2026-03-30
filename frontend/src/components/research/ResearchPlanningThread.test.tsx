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
      })
    );

    expect(html).toContain('帮我研究适合 20 人团队的 MCP 部署方案');
    expect(html).toContain('你更关注内部研发团队，还是对外客户交付？');
    expect(html).toContain('受众不同，会影响部署复杂度、权限模型和评估重点。');
    expect(html).not.toContain('确认计划并开始研究');
  });

  it('renders the plan message and confirmation CTA when awaiting confirmation', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchPlanningThread, {
        question: '比较 Tavily、Jina Reader 与 SearXNG 的研究入口定位',
        status: 'awaiting_confirmation',
        planSnapshot: {
          research_brief: '比较三种外部检索入口在研究工作台中的角色分工',
          complexity: 'comparative',
          summary: '先对齐能力边界，再比较响应质量、证据稳定性与运维成本。',
          subtasks: [
            {
              title: '能力边界',
              description: '梳理每种入口的覆盖范围与适用阶段。',
              target_sources: ['web', 'paper'],
            },
          ],
          target_sources: ['web', 'paper'],
          budget_guidance: '优先使用官方文档与公开技术资料。',
          confirmation_required: true,
        },
        onConfirm: () => undefined,
      })
    );

    expect(html).toContain('比较 Tavily、Jina Reader 与 SearXNG 的研究入口定位');
    expect(html).toContain('计划草案');
    expect(html).toContain('先对齐能力边界，再比较响应质量、证据稳定性与运维成本。');
    expect(html).toContain('确认计划并开始研究');
  });
});

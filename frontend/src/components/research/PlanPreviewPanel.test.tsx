import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { PlanPreviewPanel } from './PlanPreviewPanel';

describe('PlanPreviewPanel', () => {
  it('renders plan content with the new confirmation CTA wording', () => {
    const html = renderToStaticMarkup(
      createElement(PlanPreviewPanel, {
        status: 'awaiting_confirmation',
        planSnapshot: {
          research_brief: '围绕铁路调度策略做深度研究',
          complexity: 'comparative',
          summary: '先比较两种路线，再补网页证据。',
          subtasks: [
            {
              title: '比较方案',
              description: '输出方案差异与权衡',
              target_sources: ['paper', 'web'],
            },
          ],
          target_sources: ['paper', 'web'],
          budget_guidance: '优先论文，再补网页。',
          confirmation_required: true,
        },
        onConfirm: () => undefined,
      })
    );

    expect(html).toContain('计划草案');
    expect(html).toContain('围绕铁路调度策略做深度研究');
    expect(html).toContain('先比较两种路线，再补网页证据。');
    expect(html).toContain('paper');
    expect(html).toContain('web');
    expect(html).toContain('确认计划并开始研究');
  });
});

import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchSessionRail } from './ResearchSessionRail';

describe('ResearchSessionRail', () => {
  it('renders status, plan, source summary and resume controls for interrupted sessions', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchSessionRail, {
        question: '比较调度路线',
        statusLabel: '已中断',
        statusTone: 'pending',
        progressItems: [
          {
            id: '1',
            title: '已完成路线比较',
            phaseLabel: 'analysis',
            providerLabel: 'tavily',
            sourceLabel: null,
            finding: null,
          },
        ],
        sourceSummary: {
          heading: '研究来源',
          modeLabel: '网络搜索深度研究',
          helperText: '当前仅使用联网检索与外部资料完成研究。',
        },
        planPanel: createElement('div', null, '计划卡'),
        interruptPanel: createElement('div', null, '继续研究'),
        advancedEventsPanel: createElement('div', null, '高级事件'),
        onReset: () => undefined,
      })
    );

    expect(html).toContain('比较调度路线');
    expect(html).toContain('已中断');
    expect(html).toContain('计划卡');
    expect(html).toContain('继续研究');
    expect(html).toContain('网络搜索深度研究');
  });
});

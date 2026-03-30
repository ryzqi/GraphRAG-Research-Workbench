import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchSourceSummary } from './ResearchSourceSummary';

describe('ResearchSourceSummary', () => {
  it('renders network research summary', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchSourceSummary, {
        summary: {
          heading: '研究来源',
          modeLabel: '网络搜索深度研究',
          helperText: '当前仅使用联网检索与外部资料完成研究。',
        },
      })
    );

    expect(html).toContain('研究来源');
    expect(html).toContain('网络搜索深度研究');
  });
});

import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchProgressFeed } from './ResearchProgressFeed';

describe('ResearchProgressFeed', () => {
  it('renders the human-readable progress heading', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchProgressFeed, {
        items: [
          {
            id: '1',
            title: '已完成路线比较',
            phaseLabel: 'analysis',
            providerLabel: 'tavily',
            sourceLabel: null,
            finding: '发现显著差异',
          },
        ],
      })
    );

    expect(html).toContain('研究进度');
    expect(html).toContain('已完成路线比较');
  });
});

import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchWorkspaceShell } from './ResearchWorkspaceShell';

describe('ResearchWorkspaceShell', () => {
  it('renders execution handoff copy after the plan is confirmed', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchWorkspaceShell, {
        rail: createElement('section', null, '左栏内容'),
        canvas: createElement('section', null, '右栏内容'),
      })
    );

    expect(html).toContain('研究工作台');
    expect(html).toContain('计划已确认，下面展示执行进度、发现与产物。');
    expect(html).toContain('左栏内容');
    expect(html).toContain('右栏内容');
  });
});

import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchWorkspaceShell } from './ResearchWorkspaceShell';

describe('ResearchWorkspaceShell', () => {
  it('renders subtle status copy and an expanded right sidebar by default', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchWorkspaceShell, {
        statusLine: '研究中…',
        sidebarOpen: true,
        onToggleSidebar: () => undefined,
        rail: createElement('section', null, '左栏内容'),
        canvas: createElement('section', null, '右栏内容'),
      })
    );

    expect(html).toContain('研究中…');
    expect(html).toContain('收起侧栏');
    expect(html).toContain('左栏内容');
    expect(html).toContain('右栏内容');
  });

  it('hides the sidebar content when collapsed', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchWorkspaceShell, {
        statusLine: '已完成',
        sidebarOpen: false,
        onToggleSidebar: () => undefined,
        rail: createElement('section', null, '左栏内容'),
        canvas: createElement('section', null, '右栏内容'),
      })
    );

    expect(html).toContain('显示侧栏');
    expect(html).toContain('右栏内容');
    expect(html).not.toContain('左栏内容');
  });
});

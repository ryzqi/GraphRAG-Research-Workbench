import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchWorkspaceShell } from './ResearchWorkspaceShell';

describe('ResearchWorkspaceShell', () => {
  it('renders mission control, plan rail, canvas, and evidence ledger when expanded', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchWorkspaceShell, {
        statusLine: '研究中…',
        sidebarOpen: true,
        onToggleSidebar: () => undefined,
        missionControl: createElement('section', null, 'Mission Control'),
        rail: createElement('section', null, 'Plan Rail'),
        canvas: createElement('section', null, 'Canvas'),
        ledger: createElement('section', null, 'Evidence Ledger'),
      })
    );

    expect(html).toContain('研究中…');
    expect(html).toContain('收起侧栏');
    expect(html).toContain('Mission Control');
    expect(html).toContain('Plan Rail');
    expect(html).toContain('Canvas');
    expect(html).toContain('Evidence Ledger');
  });

  it('hides only the plan rail when collapsed', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchWorkspaceShell, {
        statusLine: '已完成',
        sidebarOpen: false,
        onToggleSidebar: () => undefined,
        missionControl: createElement('section', null, 'Mission Control'),
        rail: createElement('section', null, 'Plan Rail'),
        canvas: createElement('section', null, 'Canvas'),
        ledger: createElement('section', null, 'Evidence Ledger'),
      })
    );

    expect(html).toContain('显示侧栏');
    expect(html).toContain('Mission Control');
    expect(html).toContain('Canvas');
    expect(html).toContain('Evidence Ledger');
    expect(html).not.toContain('Plan Rail');
  });
});

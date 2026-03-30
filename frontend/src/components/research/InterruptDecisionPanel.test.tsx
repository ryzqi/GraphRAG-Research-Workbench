import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { InterruptDecisionPanel } from './InterruptDecisionPanel';

describe('InterruptDecisionPanel', () => {
  it('renders resume controls when the session is interrupted', () => {
    const html = renderToStaticMarkup(
      createElement(InterruptDecisionPanel, {
        status: 'interrupted',
        resumeIdempotencyKey: 'resume-1',
        decisionDraft: '[{\"action\":\"approve\"}]',
        onResumeIdempotencyKeyChange: vi.fn(),
        onDecisionDraftChange: vi.fn(),
        onResume: vi.fn(),
        resumePending: false,
      })
    );

    expect(html).toContain('中断决策');
    expect(html).toContain('继续研究');
    expect(html).toContain('高级决策');
  });
});

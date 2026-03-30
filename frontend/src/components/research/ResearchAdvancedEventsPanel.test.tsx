import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchAdvancedEventsPanel } from './ResearchAdvancedEventsPanel';

describe('ResearchAdvancedEventsPanel', () => {
  it('renders advanced event details separately from the main feed', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchAdvancedEventsPanel, {
        events: [
          {
            event_id: 'evt-0002',
            sequence: 2,
            timestamp: '2026-03-30T00:00:02Z',
            event_type: 'research.run.started',
            session_id: 'session-1',
            phase: 'runtime',
            namespace: 'web/researcher',
            payload: {},
            source_provider: 'searxng',
            retrieval_method: 'search',
            origin_url: 'https://example.com/web',
            subagent_name: 'researcher',
          },
        ],
      })
    );

    expect(html).toContain('高级事件');
    expect(html).toContain('技术事件');
  });
});

import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchTimeline } from './ResearchTimeline';

describe('ResearchTimeline', () => {
  it('renders ordered events with namespace and provider context', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchTimeline, {
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
          {
            event_id: 'evt-0001',
            sequence: 1,
            timestamp: '2026-03-30T00:00:01Z',
            event_type: 'research.plan.created',
            session_id: 'session-1',
            phase: 'planner',
            namespace: 'main',
            payload: {},
            source_provider: null,
            retrieval_method: null,
            origin_url: null,
            subagent_name: null,
          },
        ],
      })
    );

    expect(html).toContain('研究时间线');
    expect(html.indexOf('research.plan.created')).toBeLessThan(html.indexOf('research.run.started'));
    expect(html).toContain('main');
    expect(html).toContain('web/researcher');
    expect(html).toContain('searxng');
  });
});

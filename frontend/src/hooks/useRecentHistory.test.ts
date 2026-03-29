import { describe, expect, it } from 'vitest';

import { toRecentHistoryData } from './useRecentHistory';

describe('toRecentHistoryData', () => {
  it('preserves structured web search status instead of collapsing it to a single boolean', () => {
    const result = toRecentHistoryData({
      items: [
        {
          id: 'session-1',
          title: '最新模型价格',
          session_type: 'general_chat',
          updated_at: '2026-03-25T12:00:00Z',
        },
      ],
      web_search: {
        configured: true,
        verified: true,
        mode: 'degraded',
        providers: [
          {
            name: 'tavily',
            configured: true,
            verified: true,
            healthy: true,
            mode: 'healthy',
            latency_ms: 420,
            error: null,
          },
          {
            name: 'searxng',
            configured: true,
            verified: true,
            healthy: false,
            mode: 'down',
            latency_ms: 5000,
            error: 'timeout',
          },
        ],
      },
    });

    expect(result).toEqual({
      sessions: [
        {
          sessionId: 'session-1',
          title: '最新模型价格',
          type: 'general_chat',
          updatedAt: '2026-03-25T12:00:00Z',
        },
      ],
      webSearch: {
        configured: true,
        verified: true,
        mode: 'degraded',
        providers: [
          {
            name: 'tavily',
            configured: true,
            verified: true,
            healthy: true,
            mode: 'healthy',
            latency_ms: 420,
            error: null,
          },
          {
            name: 'searxng',
            configured: true,
            verified: true,
            healthy: false,
            mode: 'down',
            latency_ms: 5000,
            error: 'timeout',
          },
        ],
      },
    });
  });
});

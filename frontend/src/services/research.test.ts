import { beforeEach, describe, expect, it, vi } from 'vitest';

import { apiFetch } from './http';
import { openSseStream } from './sse';
import {
  createResearchSession,
  confirmResearchPlan,
  getResearchArtifacts,
  streamResearchSession,
} from './research';
import { mergeResearchEventEnvelopes } from '../types/researchEvents';

vi.mock('./http', () => ({
  apiFetch: vi.fn(),
}));

vi.mock('./sse', () => ({
  openSseStream: vi.fn(),
}));

describe('research service contract', () => {
  const apiFetchMock = vi.mocked(apiFetch);
  const openSseStreamMock = vi.mocked(openSseStream);
  const emptyStream = {
    async *[Symbol.asyncIterator]() {
      return;
    },
  };

  beforeEach(() => {
    apiFetchMock.mockReset();
    openSseStreamMock.mockReset();
  });

  it('creates research sessions through the current session endpoint', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'session-1',
      status: 'queued',
      plan_snapshot: null,
    });

    await createResearchSession({
      question: '请比较两种路线',
      selected_kb_ids: ['kb-1'],
      allow_external: true,
      require_confirmation: false,
    });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/research/sessions', {
      method: 'POST',
      body: JSON.stringify({
        question: '请比较两种路线',
        selected_kb_ids: ['kb-1'],
        allow_external: true,
        require_confirmation: false,
      }),
    });
  });

  it('confirms plan through the current confirm-plan endpoint', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'session-1',
      status: 'queued',
      plan_snapshot: null,
    });

    await confirmResearchPlan('session-1', {
      approved: true,
      note: '继续执行',
    });

    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/research/sessions/session-1/confirm-plan',
      {
        method: 'POST',
        body: JSON.stringify({
          approved: true,
          note: '继续执行',
        }),
      }
    );
  });

  it('reads research artifacts through the current artifacts endpoint', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'session-1',
      items: [],
    });

    await getResearchArtifacts('session-1');

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/research/sessions/session-1/artifacts');
  });

  it('streams research sessions with Last-Event-ID priority and resume fallback query', async () => {
    openSseStreamMock.mockResolvedValue(emptyStream);

    await streamResearchSession('session-1', {
      lastEventId: 'evt-0002',
      resumeFromEventId: 'evt-0001',
    });

    expect(openSseStreamMock).toHaveBeenCalledWith(
      '/api/v1/research/sessions/session-1/stream?resume_from_event_id=evt-0001',
      {
        method: 'GET',
        headers: {
          'Last-Event-ID': 'evt-0002',
        },
      },
      undefined
    );
  });
});

describe('mergeResearchEventEnvelopes', () => {
  it('deduplicates by event_id and keeps events ordered by sequence', () => {
    const merged = mergeResearchEventEnvelopes(
      [
        {
          event_id: 'evt-0001',
          sequence: 1,
          timestamp: '2026-03-29T00:00:00Z',
          event_type: 'research.plan.created',
          session_id: 'session-1',
          phase: 'planner',
          namespace: 'main',
          payload: { summary: 'plan' },
          trace_id: null,
          source_provider: null,
          retrieval_method: null,
          origin_url: null,
          subagent_name: null,
        },
      ],
      [
        {
          event_id: 'evt-0003',
          sequence: 3,
          timestamp: '2026-03-29T00:00:03Z',
          event_type: 'research.final.completed',
          session_id: 'session-1',
          phase: 'finalizer',
          namespace: 'main',
          payload: {},
          trace_id: null,
          source_provider: null,
          retrieval_method: null,
          origin_url: null,
          subagent_name: null,
        },
        {
          event_id: 'evt-0002',
          sequence: 2,
          timestamp: '2026-03-29T00:00:02Z',
          event_type: 'research.run.started',
          session_id: 'session-1',
          phase: 'runtime',
          namespace: 'main',
          payload: {},
          trace_id: null,
          source_provider: 'tavily',
          retrieval_method: 'search',
          origin_url: 'https://example.com',
          subagent_name: 'web',
        },
        {
          event_id: 'evt-0002',
          sequence: 2,
          timestamp: '2026-03-29T00:00:02Z',
          event_type: 'research.run.started',
          session_id: 'session-1',
          phase: 'runtime',
          namespace: 'main',
          payload: {},
          trace_id: null,
          source_provider: 'tavily',
          retrieval_method: 'search',
          origin_url: 'https://example.com',
          subagent_name: 'web',
        },
      ]
    );

    expect(merged.map((item) => item.event_id)).toEqual(['evt-0001', 'evt-0002', 'evt-0003']);
    expect(merged.map((item) => item.sequence)).toEqual([1, 2, 3]);
    expect(merged[1]).toMatchObject({
      namespace: 'main',
      source_provider: 'tavily',
      retrieval_method: 'search',
      subagent_name: 'web',
    });
  });
});

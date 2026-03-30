import { beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest';

import { apiFetch } from './http';
import { openSseStream } from './sse';
import {
  createResearchSession,
  confirmResearchPlan,
  type ResearchClarificationRequest,
  type ResearchEventEnvelope,
  type ResearchSessionAccepted,
  type ResearchSessionStatus,
  getResearchArtifacts,
  streamResearchSession,
} from './research';
import {
  deriveResearchStatus,
  mergeResearchEventEnvelopes,
} from '../types/researchEvents';

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
    });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/research/sessions', {
      method: 'POST',
      body: JSON.stringify({
        question: '请比较两种路线',
        plan_first: true,
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

describe('deriveResearchStatus', () => {
  it('maps research.run.failed to failed', () => {
    const events: ResearchEventEnvelope[] = [
      {
        event_id: 'evt-0009',
        sequence: 9,
        timestamp: '2026-03-30T00:00:09Z',
        event_type: 'research.run.failed',
        session_id: 'session-1',
        phase: 'runtime',
        namespace: 'main',
        payload: {},
      },
    ];

    expect(
      deriveResearchStatus({
        acceptedStatus: 'queued',
        events,
        artifacts: [],
      })
    ).toBe('failed');
  });
});

describe('research type contract', () => {
  it('supports clarifying status and clarification payloads', () => {
    expectTypeOf<Extract<ResearchSessionStatus, 'clarifying'>>().toEqualTypeOf<'clarifying'>();
    expectTypeOf<ResearchClarificationRequest>().toMatchObjectType<{
      summary: string;
      questions: Array<{
        id: string;
        question: string;
        why_it_matters: string;
      }>;
    }>();

    const accepted: ResearchSessionAccepted = {
      session_id: 'session-clarifying',
      status: 'clarifying',
      plan_snapshot: null,
      clarification_request: {
        summary: '研究范围还不够明确，需要先补充一点背景。',
        questions: [
          {
            id: 'scope',
            question: '你希望输出个人选型建议，还是团队采购建议？',
            why_it_matters: '目标读者不同，会直接影响评估维度与结论粒度。',
          },
        ],
      },
    };

    expect(accepted.status).toBe('clarifying');
    expect(accepted.clarification_request?.questions[0]?.id).toBe('scope');
  });
});

import { beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest';

import { apiFetch } from './http';
import { openSseStream } from './sse';
import {
  createResearchSession,
  startResearchSession,
  stopResearchSession,
  updateResearchPlan,
  submitResearchClarification,
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
      status: 'plan_ready',
      plan_snapshot: {
        research_brief: '比较三种研究入口的能力边界',
        complexity: 'comparative',
        summary: '先展示计划，等待用户显式开始。',
        subtasks: [],
        target_sources: ['web'],
      },
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
      timeoutMs: 300_000,
    });
  });

  it('updates the current research plan through the plan endpoint', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'session-1',
      status: 'plan_ready',
      plan_snapshot: {
        research_brief: '更新后的研究简报',
        complexity: 'comparative',
        summary: '按新反馈重排执行顺序。',
        subtasks: [],
        target_sources: ['web'],
      },
      clarification_request: null,
    });

    await updateResearchPlan('session-1', {
      feedback: '把工业界实践提前到第二步，并强调最终输出给技术负责人。',
    });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/research/sessions/session-1/plan', {
      method: 'POST',
      body: JSON.stringify({
        feedback: '把工业界实践提前到第二步，并强调最终输出给技术负责人。',
      }),
      timeoutMs: 300_000,
    });
  });

  it('starts a ready research session through the explicit start endpoint', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'session-1',
      status: 'queued',
      plan_snapshot: {
        research_brief: '比较三种研究入口的能力边界',
        complexity: 'comparative',
        summary: '用户已确认计划，开始执行。',
        subtasks: [],
        target_sources: ['web'],
      },
      clarification_request: null,
    });

    await startResearchSession('session-1');

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/research/sessions/session-1/start', {
      method: 'POST',
    });
  });

  it('stops an active research session through the stop endpoint', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'session-1',
      status: 'canceled',
      plan_snapshot: null,
      clarification_request: null,
    });

    await stopResearchSession('session-1', { reason: '用户停止本次研究' });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/research/sessions/session-1/stop', {
      method: 'POST',
      body: JSON.stringify({ reason: '用户停止本次研究' }),
    });
  });

  it('submits clarification answers through the clarification endpoint', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'session-1',
      status: 'queued',
      plan_snapshot: {
        research_brief: '比较三种研究入口的能力边界',
        complexity: 'comparative',
        summary: '补充信息后直接开始研究。',
        subtasks: [],
        target_sources: ['web'],
      },
      clarification_request: null,
    });

    await submitResearchClarification('session-1', {
      answer: '面向 20 人研发团队，输出选型建议与落地顺序。',
    });

    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/research/sessions/session-1/clarification',
      {
        method: 'POST',
        body: JSON.stringify({
          answer: '面向 20 人研发团队，输出选型建议与落地顺序。',
        }),
        timeoutMs: 300_000,
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
          event_type: 'research.plan.ready',
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
  it('maps research.run.stopped to canceled after the hard cut stop flow', () => {
    const events: ResearchEventEnvelope[] = [
      {
        event_id: 'evt-0008',
        sequence: 8,
        timestamp: '2026-03-30T00:00:08Z',
        event_type: 'research.run.stopped',
        session_id: 'session-1',
        phase: 'runtime',
        namespace: 'main',
        payload: {},
      },
    ];

    expect(
      deriveResearchStatus({
        acceptedStatus: 'running',
        events,
        artifacts: [],
      })
    ).toBe('canceled');
  });

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
  it('supports clarifying and plan_ready status payloads', () => {
    expectTypeOf<Extract<ResearchSessionStatus, 'clarifying'>>().toEqualTypeOf<'clarifying'>();
    expectTypeOf<Extract<ResearchSessionStatus, 'plan_ready'>>().toEqualTypeOf<'plan_ready'>();
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

  it('supports plan_ready accepted payloads with plan snapshots', () => {
    const accepted: ResearchSessionAccepted = {
      session_id: 'session-plan-ready',
      status: 'plan_ready',
      plan_snapshot: {
        research_brief: '聚焦最近两年的 RAG 顶会和工业界实践',
        complexity: 'comparative',
        summary: '先给用户看计划，再决定是否开始执行。',
        subtasks: [
          {
            title: '论文检索',
            description: '收集近两年的论文。',
            target_sources: ['paper'],
          },
        ],
        target_sources: ['paper', 'web'],
      },
      clarification_request: null,
    };

    expect(accepted.status).toBe('plan_ready');
    expect(accepted.plan_snapshot?.subtasks[0]?.title).toBe('论文检索');
  });
});

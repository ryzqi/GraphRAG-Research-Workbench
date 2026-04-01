import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

const reactState = vi.hoisted(() => ({
  sequence: [] as Array<[unknown, (value: unknown) => void]>,
  index: 0,
}));

vi.mock('react', async () => {
  const actual = await vi.importActual<typeof import('react')>('react');
  return {
    ...actual,
    useState: <T,>(initialState: T) => {
      const next = reactState.sequence[reactState.index] as [T, (value: T) => void] | undefined;
      reactState.index += 1;
      return next ?? actual.useState(initialState);
    },
  };
});

const createResearchSessionMock = vi.fn();
const submitClarificationMock = vi.fn();
const interruptSessionMock = vi.fn();
const resumeSessionMock = vi.fn();
const refetchMock = vi.fn();

const hookState = {
  session: undefined as
    | {
        session_id: string;
        status: 'clarifying' | 'queued' | 'running';
        plan_snapshot: {
          research_brief: string;
          complexity: 'simple' | 'comparative' | 'complex';
          summary: string;
          subtasks: [];
          target_sources: ['web'];
        } | null;
        clarification_request: {
          summary: string;
          questions: Array<{
            id: string;
            question: string;
            why_it_matters: string;
          }>;
        } | null;
        events: [];
        artifacts: [];
        last_event_id: null;
        last_sequence: number;
        report_md: null;
        report_json: null;
      }
    | undefined,
};

vi.mock('../hooks/queries/useResearch', () => ({
  useCreateResearchSession: () => ({
    isPending: false,
    error: null,
    mutateAsync: createResearchSessionMock,
    reset: vi.fn(),
  }),
  useSubmitResearchClarification: () => ({
    isPending: false,
    error: null,
    mutateAsync: submitClarificationMock,
    reset: vi.fn(),
  }),
  useInterruptResearchSession: () => ({
    isPending: false,
    error: null,
    mutateAsync: interruptSessionMock,
    reset: vi.fn(),
  }),
  useResumeResearchSession: () => ({
    isPending: false,
    error: null,
    mutateAsync: resumeSessionMock,
    reset: vi.fn(),
  }),
  useResearchSession: () => ({
    data: hookState.session,
    error: null,
    isPending: false,
    isFetching: false,
    streamStatus: 'idle',
    refetch: refetchMock,
  }),
}));

import { ResearchPage } from './ResearchPage';

afterEach(() => {
  hookState.session = undefined;
  reactState.sequence = [];
  reactState.index = 0;
});

describe('ResearchPage', () => {
  it('renders the new composer before a session exists', () => {
    const html = renderToStaticMarkup(createElement(ResearchPage));

    expect(html).toContain('有问题，尽管问');
    expect(html).toContain('开始研究');
    expect(html).not.toContain('先规划，再开始研究');
  });

  it('renders the workspace shell when a session is active', () => {
    hookState.session = {
      session_id: 'session-1',
      status: 'running',
      plan_snapshot: null,
      clarification_request: null,
      events: [],
      artifacts: [
        {
          artifact_key: 'mission_md',
          content_text: '# Mission\n\n比较调度路线',
          citations: [],
        },
        {
          artifact_key: 'plan_md',
          content_text: '# Plan\n\n## Subtasks\n- 对齐控制面\n- 检查证据账本',
          citations: [],
        },
        {
          artifact_key: 'source_ledger_json',
          content_json: [
            {
              provider: 'tavily',
              title: '路线对比',
              origin_url: 'https://example.com/routes',
              source_type: 'web',
            },
          ],
          citations: [],
        },
      ],
      last_event_id: null,
      last_sequence: 0,
      report_md: null,
      report_json: null,
    };

    const setState = vi.fn();
    reactState.sequence = [
      ['比较调度路线', setState],
      ['session-1', setState],
      [
        {
          session_id: 'session-1',
          status: 'running',
          plan_snapshot: null,
          clarification_request: null,
        },
        setState,
      ],
      [false, setState],
      [null, setState],
      ['', setState],
      ['resume-1', setState],
      ['[{"action":"approve"}]', setState],
      [true, setState],
    ];
    reactState.index = 0;

    const html = renderToStaticMarkup(createElement(ResearchPage));

    expect(html).toContain('研究中…');
    expect(html).toContain('Mission Control');
    expect(html).toContain('Evidence Ledger');
    expect(html).toContain('比较调度路线');
    expect(html).toContain('路线对比');
    expect(html).toContain('收起侧栏');
  });

  it('renders the planning thread with clarification questions instead of the workspace', () => {
    hookState.session = {
      session_id: 'session-clarifying',
      status: 'clarifying',
      plan_snapshot: null,
      clarification_request: {
        summary: '还需要补充研究上下文。',
        questions: [
          {
            id: 'scope',
            question: '你希望输出选型建议，还是迁移实施方案？',
            why_it_matters: '目标不同，规划结构会不同。',
          },
        ],
      },
      events: [],
      artifacts: [],
      last_event_id: null,
      last_sequence: 0,
      report_md: null,
      report_json: null,
    };

    const setState = vi.fn();
    reactState.sequence = [
      ['MCP 部署研究', setState],
      ['session-clarifying', setState],
      [
        {
          session_id: 'session-clarifying',
          status: 'clarifying',
          plan_snapshot: null,
          clarification_request: hookState.session.clarification_request,
        },
        setState,
      ],
      [false, setState],
      [null, setState],
      ['面向 20 人研发团队。', setState],
      ['resume-1', setState],
      ['[{"action":"approve"}]', setState],
      [true, setState],
    ];
    reactState.index = 0;

    const html = renderToStaticMarkup(createElement(ResearchPage));

    expect(html).toContain('你希望输出选型建议，还是迁移实施方案？');
    expect(html).toContain('提交补充信息');
    expect(html).not.toContain('Mission Control');
    expect(html).not.toContain('Evidence Ledger');
    expect(html).not.toContain('失败');
  });

  it('shows an explicit contract error state instead of silently empty evidence sections', () => {
    hookState.session = {
      session_id: 'session-invalid-artifact',
      status: 'running',
      plan_snapshot: null,
      clarification_request: null,
      events: [],
      artifacts: [
        {
          artifact_key: 'mission_md',
          content_text: '# Mission\n\n检查 contract drift',
          citations: [],
        },
        {
          artifact_key: 'source_ledger_json',
          content_json: {
            provider: 'tavily',
          },
          citations: [],
        },
      ],
      last_event_id: null,
      last_sequence: 0,
      report_md: null,
      report_json: null,
    };

    const setState = vi.fn();
    reactState.sequence = [
      ['检查 contract drift', setState],
      ['session-invalid-artifact', setState],
      [
        {
          session_id: 'session-invalid-artifact',
          status: 'running',
          plan_snapshot: null,
          clarification_request: null,
        },
        setState,
      ],
      [false, setState],
      [null, setState],
      ['', setState],
      ['resume-1', setState],
      ['[{"action":"approve"}]', setState],
      [true, setState],
    ];
    reactState.index = 0;

    const html = renderToStaticMarkup(createElement(ResearchPage));

    expect(html).toContain('证据工件格式错误');
    expect(html).toContain('source_ledger_json 格式无效：期望数组');
  });

});

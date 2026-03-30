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
const confirmPlanMock = vi.fn();
const interruptSessionMock = vi.fn();
const resumeSessionMock = vi.fn();
const refetchMock = vi.fn();

const hookState = {
  session: undefined as
    | {
        session_id: string;
        status: 'running';
        plan_snapshot: null;
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
  useConfirmResearchPlan: () => ({
    isPending: false,
    error: null,
    mutateAsync: confirmPlanMock,
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

    expect(html).toContain('先规划，再开始研究');
    expect(html).toContain('生成研究计划');
  });

  it('renders the workspace shell when a session is active', () => {
    hookState.session = {
      session_id: 'session-1',
      status: 'running',
      plan_snapshot: null,
      events: [],
      artifacts: [],
      last_event_id: null,
      last_sequence: 0,
      report_md: null,
      report_json: null,
    };

    const setState = vi.fn();
    reactState.sequence = [
      ['比较调度路线', setState],
      ['session-1', setState],
      [{ session_id: 'session-1', status: 'running', plan_snapshot: null }, setState],
      [false, setState],
      [null, setState],
      ['resume-1', setState],
      ['[{"action":"approve"}]', setState],
    ];
    reactState.index = 0;

    const html = renderToStaticMarkup(createElement(ResearchPage));

    expect(html).toContain('研究工作台');
  });
});

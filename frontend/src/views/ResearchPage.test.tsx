import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ResearchSessionView } from '../types/researchEvents';

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
const updatePlanMock = vi.fn();
const startSessionMock = vi.fn();
const stopSessionMock = vi.fn();
const refetchMock = vi.fn();

const hookState = {
  session: undefined as ResearchSessionView | undefined,
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
  useUpdateResearchPlan: () => ({
    isPending: false,
    error: null,
    mutateAsync: updatePlanMock,
    reset: vi.fn(),
  }),
  useStartResearchSession: () => ({
    isPending: false,
    error: null,
    mutateAsync: startSessionMock,
    reset: vi.fn(),
  }),
  useStopResearchSession: () => ({
    isPending: false,
    error: null,
    mutateAsync: stopSessionMock,
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
    expect(html).not.toContain('Deep Research');
    expect(html).not.toContain('用研究工作台，把问题拆清、证据拉齐、报告收口');
    expect(html).not.toContain(
      '对齐 Gemini 风格的轻量研究入口：先聚焦问题，再进入规划、执行与最终报告。'
    );
    expect(html).not.toContain('先规划，再开始研究');
    expect(html).not.toContain('linear-gradient(180deg,#f8fbff 0%,#eef4ff 48%,#f8fbff 100%)');
    expect(html).not.toContain('max-width:880px');
  });

  it('renders the immersive research stream when a session is active', () => {
    hookState.session = {
      session_id: 'session-1',
      status: 'running',
      plan_snapshot: null,
      clarification_request: null,
      events: [
        {
          event_id: 'evt-1',
          sequence: 1,
          timestamp: '2026-03-30T10:00:02Z',
          event_type: 'research.run.started',
          session_id: 'session-1',
          phase: 'runtime',
          namespace: 'main',
          payload: { summary: '开始调度研究' },
          source_provider: 'tavily',
          retrieval_method: 'search',
        },
        {
          event_id: 'evt-2',
          sequence: 2,
          timestamp: '2026-03-30T10:00:03Z',
          event_type: 'research.trace.recorded',
          session_id: 'session-1',
          phase: 'retrieval',
          namespace: 'main',
          payload: { summary: '抓取到两篇网页证据', finding: '两条路线在时效性上差异明显' },
          source_provider: 'searxng',
          retrieval_method: 'search',
          origin_url: 'https://example.com/routes',
        },
      ],
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
    expect(html).toContain('研究时间流');
    expect(html).toContain('比较调度路线');
    expect(html).toContain('抓取到两篇网页证据');
    expect(html).toContain('查看来源与证据');
    expect(html).not.toContain('linear-gradient(180deg,#f7faff 0%,#eef4ff 45%,#f8fbff 100%)');
    expect(html).not.toContain('radial-gradient(circle at top,rgba(66,133,244,0.18) 0%,rgba(66,133,244,0) 42%)');
    expect(html).not.toContain('max-width:1040px');
    expect(html).not.toContain('Mission Control');
    expect(html).not.toContain('Evidence Ledger');
    expect(html).not.toContain('收起侧栏');
    expect(html).not.toContain('高级事件');
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
    expect(html).not.toContain('你的研究问题');
    expect(html).not.toContain('研究助手');
    expect(html).not.toContain('在开始规划前，还需要补充一点信息');
    expect(html).not.toContain('补充你的回答');
    expect(html).not.toContain('max-width:920px');
    expect(html).not.toContain('max-width:860px');
    expect(html).not.toContain('Mission Control');
    expect(html).not.toContain('Evidence Ledger');
    expect(html).not.toContain('失败');
  });

  it('renders a plan review surface with update-plan and explicit start actions before execution', () => {
    hookState.session = {
      session_id: 'session-plan-ready',
      status: 'plan_ready',
      plan_snapshot: {
        research_brief: '聚焦最近两年的 RAG 研究与工业实践',
        complexity: 'comparative',
        summary: '先核对检索范围与输出结构，再决定是否开始执行。',
        subtasks: [
          {
            title: '检索近两年论文',
            description: '优先顶会与期刊论文。',
            target_sources: ['paper'],
          },
          {
            title: '汇总工业界实践',
            description: '补充公司博客与开源项目发布说明。',
            target_sources: ['web'],
          },
        ],
        target_sources: ['paper', 'web'],
      },
      clarification_request: null,
      events: [],
      artifacts: [],
      last_event_id: null,
      last_sequence: 0,
      report_md: null,
      report_json: null,
    };

    const setState = vi.fn();
    reactState.sequence = [
      ['当前RAG领域的最新进展', setState],
      ['session-plan-ready', setState],
      [
        {
          session_id: 'session-plan-ready',
          status: 'plan_ready',
          plan_snapshot: hookState.session.plan_snapshot,
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

    expect(html).toContain('研究计划');
    expect(html).toContain('检索近两年论文');
    expect(html).toContain('汇总工业界实践');
    expect(html).toContain('更新计划');
    expect(html).toContain('开始');
    expect(html).not.toContain('max-width:920px');
    expect(html).not.toContain('max-width:860px');
    expect(html).not.toContain('请求中断');
    expect(html).not.toContain('研究时间流');
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

  it('switches to a pure report page after the final report is generated', () => {
    hookState.session = {
      session_id: 'session-final',
      status: 'final',
      plan_snapshot: null,
      clarification_request: null,
      events: [],
      artifacts: [],
      last_event_id: null,
      last_sequence: 0,
      report_md: '# 最终报告\n\n正式结论',
      report_json: { status: 'ok' },
    };

    const setState = vi.fn();
    reactState.sequence = [
      ['比较调度路线', setState],
      ['session-final', setState],
      [
        {
          session_id: 'session-final',
          status: 'final',
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

    expect(html).toContain('最终报告');
    expect(html).toContain('正式结论');
    expect(html).not.toContain('max-width:1040px');
    expect(html).not.toContain('研究时间流');
  });

  it('renders markdown converted from report_json when report_md is missing', () => {
    hookState.session = {
      session_id: 'session-json-report',
      status: 'final',
      plan_snapshot: null,
      clarification_request: null,
      events: [],
      artifacts: [
        {
          artifact_key: 'report_json',
          content_json: {
            question: '如何把 Deep Research 页面改成 Gemini 风格？',
            summary: '已完成布局、中文化与正文渲染策略分析。',
            findings: ['首页输入区应保留居中英雄区。', '最终报告正文必须统一经过 Markdown 渲染。'],
            coverage_gaps: ['仍需补一条最终态视觉回归测试。'],
            citations: [
              {
                title: 'Gemini 页面观察',
                origin_url: 'https://example.com/gemini',
              },
            ],
          },
          citations: [],
        },
      ],
      last_event_id: null,
      last_sequence: 0,
      report_md: null,
      report_json: {
        question: '如何把 Deep Research 页面改成 Gemini 风格？',
      },
    };

    const setState = vi.fn();
    reactState.sequence = [
      ['Gemini 风格工作台改版', setState],
      ['session-json-report', setState],
      [
        {
          session_id: 'session-json-report',
          status: 'final',
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

    expect(html).toContain('研究报告');
    expect(html).toContain('关键发现');
    expect(html).toContain('Gemini 页面观察');
    expect(html).not.toContain('"question"');
    expect(html).not.toContain('"findings"');
  });

});

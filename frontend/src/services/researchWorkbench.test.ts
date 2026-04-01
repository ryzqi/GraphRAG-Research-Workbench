import { describe, expect, it } from 'vitest';

import {
  buildResearchPageViewModel,
  buildResearchWorkspaceModel,
} from './researchWorkbench';
import type { ResearchArtifactRead, ResearchEventEnvelope } from '../types/researchEvents';

const runningEvents: ResearchEventEnvelope[] = [
  {
    event_id: 'evt-2',
    sequence: 2,
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
    event_id: 'evt-3',
    sequence: 3,
    timestamp: '2026-03-30T10:00:03Z',
    event_type: 'research.trace.recorded',
    session_id: 'session-1',
    phase: 'retrieval',
    namespace: 'main',
    payload: { summary: '抓取到两篇网页证据', finding: '两条路线在时效性上差异明显' },
    source_provider: 'searxng',
    retrieval_method: 'search',
    origin_url: 'https://example.com/a',
  },
];

const interimArtifacts: ResearchArtifactRead[] = [
  {
    artifact_key: 'interim_summary',
    content_text: '当前已完成路线比较，并进入证据补充阶段。',
    citations: [],
  },
  {
    artifact_key: 'coverage_gaps',
    content_json: ['仍需补充一条公开网页案例。'],
    citations: [],
  },
];

const workspaceArtifacts: ResearchArtifactRead[] = [
  {
    artifact_key: 'mission_md',
    content_text: '# Mission\n\n- Brief: 研究 LangGraph Deep Research 工作流\n',
    citations: [],
  },
  {
    artifact_key: 'plan_md',
    content_text:
      '# Plan\n\n## Summary\n先梳理控制面，再补全证据账本。\n\n## Subtasks\n- Mission Control: 明确任务视图\n- Evidence Ledger: 对齐证据结构\n',
    citations: [],
  },
  {
    artifact_key: 'coverage_md',
    content_text: '# Coverage\n\n- status: in_progress\n',
    citations: [],
  },
  {
    artifact_key: 'coverage_matrix_json',
    content_json: {
      provider_counts: { tavily: 2, searxng: 1 },
      missing_providers: ['jina'],
    },
    citations: [],
  },
  {
    artifact_key: 'source_ledger_json',
    content_json: [
      {
        provider: 'tavily',
        origin_url: 'https://example.com/a',
        title: 'Source A',
        source_type: 'web',
      },
      {
        provider: 'arxiv',
        origin_url: 'https://arxiv.org/abs/1234.5678',
        title: 'Paper B',
        source_type: 'paper',
      },
    ],
    citations: [],
  },
  {
    artifact_key: 'conflicts_json',
    content_json: [
      {
        claim: 'Evidence Ledger 仍缺少冲突列表。',
        verdict: 'contested',
        reason: 'coverage_gap',
        citation_indices: [1],
        coverage_gaps: ['jina'],
      },
    ],
    citations: [],
  },
  {
    artifact_key: 'claim_map_json',
    content_json: [
      {
        claim: 'Mission Control 需要 typed selectors。',
        verdict: 'supported',
        citation_indices: [0, 1],
      },
    ],
    citations: [],
  },
  {
    artifact_key: 'report_md',
    content_text: '# 研究报告\n\n结论已生成。',
    citations: [],
  },
  {
    artifact_key: 'report_json',
    content_json: {
      question: '什么是 Deep Research OS？',
      citations: [],
    },
    citations: [],
  },
];

describe('buildResearchPageViewModel', () => {
  it('builds immersive live timeline items before report_md exists', () => {
    const model = buildResearchPageViewModel({
      status: 'running',
      events: runningEvents,
      artifacts: interimArtifacts,
      reportMd: null,
    });

    expect(model.surface).toBe('live-research');
    expect(model.timelineItems).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          kind: 'system_status',
          title: '开始调度研究',
        }),
        expect.objectContaining({
          kind: 'web_visit',
          title: '抓取到两篇网页证据',
          url: 'https://example.com/a',
        }),
        expect.objectContaining({
          kind: 'intermediate_result',
          title: '阶段性发现',
        }),
      ])
    );
    expect(model.evidenceDrawer.coverageGap).toBe('仍需补充一条公开网页案例。');
  });

  it('promotes report_md to the pure report surface after finalization', () => {
    expect(
      buildResearchPageViewModel({
        status: 'final',
        events: runningEvents,
        artifacts: interimArtifacts,
        reportMd: '# 最终报告\n\n结论正文',
      })
    ).toMatchObject({
      surface: 'final-report',
      report: {
        markdown: '# 最终报告\n\n结论正文',
      },
    });
  });

  it('reads coverage_gaps from content_json arrays emitted by backend artifacts', () => {
    expect(
      buildResearchPageViewModel({
        status: 'running',
        events: runningEvents,
        artifacts: [
          {
            artifact_key: 'coverage_gaps',
            content_json: ['缺少来源证据：tavily', '缺少论文交叉验证'],
            citations: [],
          },
        ],
        reportMd: null,
      }).evidenceDrawer.coverageGap
    ).toBe('缺少来源证据：tavily\n缺少论文交叉验证');
  });

  it('falls back to report_json and converts it to markdown instead of exposing raw json', () => {
    expect(
      buildResearchPageViewModel({
        status: 'final',
        events: [],
        artifacts: [
          {
            artifact_key: 'report_json',
            content_json: {
              question: 'Gemini 风格研究页应该如何组织？',
              summary: '已完成页面骨架、内容层级与正文渲染策略分析。',
              findings: ['输入区应保留首页居中布局。', '最终报告正文应统一按 Markdown 渲染。'],
              coverage_gaps: ['仍需补充一条最终态视觉回归用例。'],
              citations: [
                {
                  title: 'Gemini UI 观察',
                  origin_url: 'https://example.com/gemini',
                },
              ],
            },
            citations: [],
          },
        ],
        reportMd: null,
      })
    ).toMatchObject({
      surface: 'final-report',
      report: {
        markdown: expect.stringContaining('# 研究报告'),
      },
    });

    const pageModel = buildResearchPageViewModel({
      status: 'final',
      events: [],
      artifacts: [
        {
          artifact_key: 'report_json',
          content_json: {
            question: 'Gemini 风格研究页应该如何组织？',
            summary: '已完成页面骨架、内容层级与正文渲染策略分析。',
            findings: ['输入区应保留首页居中布局。', '最终报告正文应统一按 Markdown 渲染。'],
            coverage_gaps: ['仍需补充一条最终态视觉回归用例。'],
            citations: [
              {
                title: 'Gemini UI 观察',
                origin_url: 'https://example.com/gemini',
              },
            ],
          },
          citations: [],
        },
      ],
      reportMd: null,
    });

    expect(pageModel.report?.markdown).toContain('## 关键发现');
    expect(pageModel.report?.markdown).toContain('## 参考来源');
    expect(pageModel.report?.markdown).not.toContain('"question"');
    expect(pageModel.report?.markdown).not.toContain('"findings"');
  });
});

describe('buildResearchWorkspaceModel', () => {
  it('hydrates mission, plan, coverage, evidence, claims, and report from typed artifacts', () => {
    expect(buildResearchWorkspaceModel(workspaceArtifacts)).toEqual({
      contractErrors: [],
      mission: {
        markdown: '# 研究任务\n\n- Brief: 研究 LangGraph Deep Research 工作流\n',
      },
      plan: {
        markdown:
          '# 研究计划\n\n## 摘要\n先梳理控制面，再补全证据账本。\n\n## 子任务\n- Mission Control: 明确任务视图\n- Evidence Ledger: 对齐证据结构\n',
        subtaskCount: 2,
      },
      coverage: {
        markdown: '# 覆盖情况\n\n- status: in_progress\n',
        matrix: {
          provider_counts: { tavily: 2, searxng: 1 },
          missing_providers: ['jina'],
        },
      },
      evidence: {
        sources: [
          {
            provider: 'tavily',
            origin_url: 'https://example.com/a',
            title: 'Source A',
            source_type: 'web',
          },
          {
            provider: 'arxiv',
            origin_url: 'https://arxiv.org/abs/1234.5678',
            title: 'Paper B',
            source_type: 'paper',
          },
        ],
        conflicts: [
          {
            claim: 'Evidence Ledger 仍缺少冲突列表。',
            verdict: 'contested',
            reason: 'coverage_gap',
            citation_indices: [1],
            coverage_gaps: ['jina'],
          },
        ],
      },
      claims: {
        items: [
          {
            claim: 'Mission Control 需要 typed selectors。',
            verdict: 'supported',
            citation_indices: [0, 1],
          },
        ],
      },
      report: {
        markdown: '# 研究报告\n\n结论已生成。',
        json: {
          question: '什么是 Deep Research OS？',
          citations: [],
        },
      },
    });
  });

  it('records explicit contract errors when verification artifact json shapes drift', () => {
    expect(
      buildResearchWorkspaceModel([
        {
          artifact_key: 'source_ledger_json',
          content_json: { provider: 'tavily' },
          citations: [],
        },
        {
          artifact_key: 'claim_map_json',
          content_json: { claim: 'not-an-array' },
          citations: [],
        },
        {
          artifact_key: 'coverage_matrix_json',
          content_json: ['not-an-object'],
          citations: [],
        },
      ])
    ).toMatchObject({
      contractErrors: [
        'coverage_matrix_json 格式无效：期望对象',
        'source_ledger_json 格式无效：期望数组',
        'claim_map_json 格式无效：期望数组',
      ],
      coverage: {
        matrix: {
          provider_counts: {},
          missing_providers: [],
        },
      },
      evidence: {
        sources: [],
        conflicts: [],
      },
      claims: {
        items: [],
      },
    });
  });

  it('counts only bullet items inside the Subtasks section', () => {
    expect(
      buildResearchWorkspaceModel([
        {
          artifact_key: 'plan_md',
          content_text:
            '# Plan\n\n## Subtasks\n- 子任务 A\n- 子任务 B\n\n## Notes\n- 这不是子任务\n',
          citations: [],
        },
      ]).plan.subtaskCount
    ).toBe(2);
  });
});

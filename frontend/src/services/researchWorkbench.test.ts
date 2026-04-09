import { describe, expect, it } from 'vitest';

import { buildResearchPageViewModel } from './researchWorkbench';
import type { ResearchArtifactRead, ResearchEventEnvelope } from '../types/researchEvents';

function buildArtifact(
  artifact_key: string,
  options: {
    content_text?: string | null;
    content_json?: Record<string, unknown> | unknown[] | null;
  } = {}
): ResearchArtifactRead {
  return {
    artifact_key,
    content_text: options.content_text ?? null,
    content_json: options.content_json ?? null,
    citations: [],
  };
}

function buildEvent(
  sequence: number,
  event_type: string,
  payload: Record<string, unknown> = {}
): ResearchEventEnvelope {
  return {
    event_id: `evt-${sequence}`,
    sequence,
    timestamp: `2026-04-09T12:00:0${sequence}.000Z`,
    event_type,
    session_id: 'session-1',
    phase: 'runtime',
    namespace: 'main',
    payload,
  };
}

describe('buildResearchPageViewModel', () => {
  it('prefers presentation_snapshot for final report surface', () => {
    const model = buildResearchPageViewModel({
      question: '全球人工智能半导体行业：2024年深度分析报告',
      status: 'final',
      events: [],
      artifacts: [
        buildArtifact('presentation_snapshot', {
          content_json: {
            surface: 'final',
            hero: {
              eyebrow: 'Deep Research',
              title: '全球人工智能半导体行业：2024年深度分析报告',
              subtitle: '研究报告已生成，可直接阅读与导出。',
            },
            rail: {
              steps: [
                { key: 'clarify', label: '澄清问题', state: 'complete' },
                { key: 'plan', label: '研究计划', state: 'complete' },
                { key: 'run', label: '执行研究', state: 'complete' },
                { key: 'report', label: '输出报告', state: 'current' },
              ],
            },
            report: {
              markdown: '# 研究报告\n\n## 市场概况\n内容 A',
              summary: '生成式 AI 正在重塑半导体供应链。',
              outline: [{ id: 'section-1', title: '市场概况', level: 2 }],
              metric_cards: [
                { label: '引用数', value: '12' },
                { label: '关键发现', value: '3' },
                { label: '覆盖状态', value: '通过' },
              ],
            },
          },
        }),
      ],
      reportMd: null,
    });

    expect(model.surface).toBe('final');
    expect(model.hero.title).toBe('全球人工智能半导体行业：2024年深度分析报告');
    expect(model.railSteps[3]?.state).toBe('current');
    expect(model.report?.outline[0]?.title).toBe('市场概况');
    expect(model.report?.metricCards[0]?.label).toBe('引用数');
  });

  it('falls back to legacy timeline construction when presentation_snapshot is missing', () => {
    const model = buildResearchPageViewModel({
      question: '测试研究任务',
      status: 'running',
      events: [
        buildEvent(1, 'research.run.started'),
        buildEvent(2, 'research.trace.recorded', { summary: '正在整理研究线索' }),
      ],
      artifacts: [
        buildArtifact('coverage_matrix_json', {
          content_json: {
            provider_counts: { tavily: 4, searxng: 2 },
            missing_providers: ['paper'],
          },
        }),
      ],
      reportMd: null,
    });

    expect(model.surface).toBe('live');
    expect(model.live?.timelineItems).toHaveLength(2);
    expect(model.live?.timelineItems[0]?.title).toBe('研究已启动');
    expect(model.live?.coverageLabel).toBe('已覆盖 2 个来源 / 1 个待补缺口');
  });

  it('derives report metric cards from evidence artifacts when final snapshot is missing', () => {
    const model = buildResearchPageViewModel({
      question: '测试研究任务',
      status: 'final',
      events: [],
      artifacts: [
        buildArtifact('report_md', {
          content_text: '# Research Report\n\n## 市场概况\n内容 A',
        }),
        buildArtifact('source_ledger_json', {
          content_json: [
            { provider: 'tavily', origin_url: 'https://example.com/a', title: '来源 A', source_type: 'web' },
            { provider: 'searxng', origin_url: 'https://example.com/b', title: '来源 B', source_type: 'web' },
          ],
        }),
        buildArtifact('claim_map_json', {
          content_json: [
            { claim: '结论一', verdict: 'supported', citation_indices: [1, 2] },
            { claim: '结论二', verdict: 'contested', citation_indices: [3] },
          ],
        }),
        buildArtifact('coverage_matrix_json', {
          content_json: {
            provider_counts: { tavily: 4, searxng: 2 },
            missing_providers: [],
          },
        }),
      ],
      reportMd: '# Research Report\n\n## 市场概况\n内容 A',
    });

    expect(model.surface).toBe('final');
    expect(model.report?.metricCards).toEqual([
      { label: '引用数', value: '2' },
      { label: '关键结论', value: '2' },
      { label: '证据状态', value: '覆盖完成' },
    ]);
  });
});

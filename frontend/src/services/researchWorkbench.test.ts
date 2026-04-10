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
              lead: '本研究聚合公开财报与供应链线索，重点关注 GPU、HBM 与先进封装对行业周期的再定价。',
              badge_label: '已生成研究报告',
              outline: [{ id: 'section-1', title: '市场概况', level: 2 }],
              metric_cards: [
                { label: '引用数', value: '12' },
                { label: '关键发现', value: '3' },
                { label: '覆盖状态', value: '通过' },
              ],
              chart: {
                title: '研究覆盖概览',
                bars: [
                  { label: 'GPU', value: 68, accent: 'primary' },
                  { label: 'HBM', value: 52, accent: 'secondary' },
                ],
              },
              spotlight_cards: [
                {
                  eyebrow: 'NVIDIA',
                  title: '关键参与者',
                  description: 'Blackwell 周期和 CUDA 生态仍在拉动 2024 年 AI 资本开支预期。',
                },
              ],
              outlook_cards: [
                {
                  title: '光子芯片技术',
                  description: '异构算力与高带宽互连仍是未来两个季度最值得持续跟踪的变量。',
                },
              ],
              references: ['01. IEA 半导体与算力追踪报告 2024'],
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
    expect(model.report?.badgeLabel).toBe('已生成研究报告');
    expect(model.report?.chart?.bars[0]?.label).toBe('GPU');
    expect(model.report?.spotlightCards[0]?.eyebrow).toBe('NVIDIA');
    expect(model.report?.outlookCards[0]?.title).toBe('光子芯片技术');
    expect(model.report?.references[0]).toBe('01. IEA 半导体与算力追踪报告 2024');
  });

  it('maps plan steps from presentation_snapshot live payload', () => {
    const model = buildResearchPageViewModel({
      question: '2024年全球电动汽车市场格局与补贴政策深度分析报告',
      status: 'running',
      events: [buildEvent(1, 'research.trace.recorded', { summary: '正在整理研究线索' })],
      artifacts: [
        buildArtifact('presentation_snapshot', {
          content_json: {
            surface: 'live',
            hero: {
              eyebrow: 'Deep Research',
              title: '2024年全球电动汽车市场格局与补贴政策深度分析报告',
              subtitle: '正在整合研究线索、证据与中间发现。',
            },
            rail: {
              steps: [
                { key: 'clarify', label: '澄清问题', state: 'complete' },
                { key: 'plan', label: '研究计划', state: 'complete' },
                { key: 'run', label: '执行研究', state: 'current' },
                { key: 'report', label: '输出报告', state: 'pending' },
              ],
            },
            live: {
              progress: {
                label: '研究执行中',
                percent: 50,
                current_stage_label: '语义建模',
              },
              coverage_label: '已汇总 12 条引用',
              plan_steps: [
                { key: 'plan-step-1', label: '梳理主要市场补贴政策', state: 'complete' },
                { key: 'plan-step-2', label: '语义建模', state: 'current' },
                { key: 'plan-step-3', label: '生成结论', state: 'pending' },
              ],
              activity: [
                {
                  id: 'a-1',
                  event_type: 'research.trace.recorded',
                  title: '记录来源轨迹：searxng',
                  body: '最近活跃链路：searxng / web-search',
                  phase: 'runtime',
                },
              ],
            },
          },
        }),
      ],
      reportMd: null,
    });

    expect(model.surface).toBe('live');
    expect(model.live?.planSteps).toEqual([
      { key: 'plan-step-1', label: '梳理主要市场补贴政策', state: 'complete' },
      { key: 'plan-step-2', label: '语义建模', state: 'current' },
      { key: 'plan-step-3', label: '生成结论', state: 'pending' },
    ]);
    expect(model.live?.progress.currentStageLabel).toBe('语义建模');
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

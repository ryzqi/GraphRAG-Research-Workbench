import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { ResearchPageViewModel } from '../../services/researchWorkbench';
import { ResearchReportReader, buildReportOutlineAnchors, resolveActiveReportSection } from './ResearchReportReader';

describe('ResearchReportReader', () => {
  it('builds stable anchor ids from outline items', () => {
    expect(
      buildReportOutlineAnchors([
        { id: 'section-1', title: '市场概况', level: 2 },
        { id: 'section-2', title: '产业链', level: 2 },
      ])
    ).toEqual([
      { id: 'section-1', title: '市场概况', level: 2, anchorId: 'report-section-1' },
      { id: 'section-2', title: '产业链', level: 2, anchorId: 'report-section-2' },
    ]);
  });

  it('resolves the active outline item from heading offsets', () => {
    expect(
      resolveActiveReportSection(
        [
          { anchorId: 'report-section-1', top: -120 },
          { anchorId: 'report-section-2', top: 72 },
          { anchorId: 'report-section-3', top: 420 },
        ],
        160
      )
    ).toBe('report-section-2');

    expect(
      resolveActiveReportSection(
        [
          { anchorId: 'report-section-1', top: 220 },
          { anchorId: 'report-section-2', top: 560 },
        ],
        160
      )
    ).toBe('report-section-1');
  });

  it('renders the final reader layout without legacy decoration blocks', () => {
    const model = {
      surface: 'final',
      hero: {
        eyebrow: 'Deep Research',
        title: '全球人工智能半导体行业：2024年深度分析报告',
        subtitle: '研究报告已生成，可直接阅读与导出。',
      },
      railSteps: [
        { key: 'clarify', label: '澄清问题', state: 'complete' },
        { key: 'plan', label: '研究计划', state: 'complete' },
        { key: 'run', label: '执行研究', state: 'complete' },
        { key: 'report', label: '输出报告', state: 'current' },
      ],
      report: {
        markdown: '# 研究报告\n\n## 市场概况\n内容 A\n\n## 产业链\n内容 B\n\n## 参考来源\n- 来源 A',
        summary: '生成式 AI 正在重塑半导体供应链。',
        badgeLabel: '已生成研究报告',
        outline: [
          { id: 'section-1', title: '市场概况', level: 2 },
          { id: 'section-2', title: '产业链', level: 2 },
          { id: 'section-3', title: '参考来源', level: 2 },
        ],
        metricCards: [
          { label: '引用数', value: '12' },
          { label: '关键发现', value: '3' },
          { label: '覆盖状态', value: '通过' },
        ],
        chart: {
          title: '研究覆盖概览',
          bars: [
            { label: 'GPU', value: 68, accent: 'primary' },
            { label: 'HBM', value: 52, accent: 'secondary' },
            { label: '先进封装', value: 31, accent: 'tertiary' },
          ],
        },
        spotlightCards: [
          {
            eyebrow: 'NVIDIA',
            title: '关键参与者',
            description: 'Blackwell 周期和 CUDA 生态仍在拉动 2024 年 AI 资本开支预期。',
          },
          {
            eyebrow: 'AMD',
            title: '关键参与者',
            description: 'MI300 系列为云厂商提供了第二增长曲线，也放大了先进封装供给约束。',
          },
        ],
        outlookCards: [
          {
            title: '光子芯片技术',
            description: '异构算力与高带宽互连仍是未来两个季度最值得持续跟踪的变量。',
          },
          {
            title: '存算一体架构',
            description: '功耗与带宽的协同优化正在推动 AI 加速器路线分化。',
          },
        ],
        references: [
          '01. IEA 半导体与算力追踪报告 2024',
          '02. Gartner Top Strategic Technology Trends for 2024',
        ],
      },
      evidenceDrawer: {
        coverageGap: null,
        coverageMarkdown: null,
        coverageMatrix: {
          provider_counts: {},
          missing_providers: [],
        },
        sources: [],
        claims: [],
        conflicts: [],
      },
    } as unknown as ResearchPageViewModel;

    const markup = renderToStaticMarkup(
      <ResearchReportReader model={model} actions={null} exportButton={null} />
    );

    expect(markup).toContain('全球人工智能半导体行业：2024年深度分析报告');
    expect(markup).toContain('市场概况');
    expect(markup).toContain('产业链');
    expect(markup).toContain('参考来源');
    expect(markup).toContain('引用数');
    expect(markup).toContain('覆盖状态');
    expect(markup).toContain('生成式 AI 正在重塑半导体供应链。');
    expect(markup).toContain('id="report-section-1"');
    expect(markup).toContain('id="report-section-2"');
    expect(markup).toContain('aria-current="true"');
    expect(markup).not.toContain('深度研究结果已生成');
    expect(markup).not.toContain('data-report-section=');
    expect(markup).not.toContain('研究覆盖概览');
    expect(markup).not.toContain('NVIDIA');
    expect(markup).not.toContain('AMD');
    expect(markup).not.toContain('光子芯片技术');
    expect(markup).not.toContain('存算一体架构');
    expect(markup).not.toContain('参考资料');
    expect(markup).not.toContain('01. IEA 半导体与算力追踪报告 2024');
  });
});

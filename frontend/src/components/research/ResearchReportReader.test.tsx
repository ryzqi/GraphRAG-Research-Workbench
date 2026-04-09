import { Typography } from '@mui/material';
import { isValidElement, type ComponentProps, type ReactElement, type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { ResearchReportReader } from './ResearchReportReader';
import { ResearchShell } from './ResearchShell';

type ResearchShellProps = ComponentProps<typeof ResearchShell>;

function collectElements(
  node: ReactNode,
  predicate: (
    element: ReactElement<{ children?: ReactNode; sx?: unknown; variant?: string }>
  ) => boolean
): ReactElement<{ children?: ReactNode; sx?: unknown; variant?: string }>[] {
  const matches: ReactElement<{ children?: ReactNode; sx?: unknown; variant?: string }>[] = [];

  const visit = (current: ReactNode): void => {
    if (Array.isArray(current)) {
      current.forEach(visit);
      return;
    }

    if (!isValidElement(current)) {
      return;
    }

    const element = current as ReactElement<{
      children?: ReactNode;
      sx?: unknown;
      variant?: string;
    }>;
    if (element.type === ResearchShell) {
      visit(ResearchShell(element.props as ResearchShellProps));
      return;
    }
    if (predicate(element)) {
      matches.push(element);
    }

    visit(element.props.children);
  };

  visit(node);
  return matches;
}

function flattenText(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') {
    return String(node);
  }

  if (Array.isArray(node)) {
    return node.map(flattenText).join('');
  }

  if (!isValidElement(node)) {
    return '';
  }

  const element = node as ReactElement<{ children?: ReactNode }>;
  if (element.type === ResearchShell) {
    return flattenText(ResearchShell(element.props as ResearchShellProps));
  }

  return flattenText(element.props.children);
}

describe('ResearchReportReader', () => {
  it('renders report outline and metric cards in the final reader layout', () => {
    const tree = ResearchReportReader({
      model: {
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
          markdown: '# 研究报告\n\n## 市场概况\n内容 A',
          summary: '生成式 AI 正在重塑半导体供应链。',
          lead: '本研究聚合公开财报与供应链线索，重点关注 GPU、HBM 与先进封装对行业周期的再定价。',
          badgeLabel: '已生成研究报告',
          outline: [{ id: 'section-1', title: '市场概况', level: 2 }],
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
      },
      actions: null,
      exportButton: null,
    });

    expect(flattenText(tree)).toContain('研究报告');
    expect(flattenText(tree)).toContain('报告摘要');
    expect(flattenText(tree)).toContain('全球人工智能半导体行业：2024年深度分析报告');
    expect(flattenText(tree)).toContain('市场概况');
    expect(flattenText(tree)).toContain('引用数');
    expect(flattenText(tree)).toContain('覆盖状态');
    expect(flattenText(tree)).toContain('研究覆盖概览');
    expect(flattenText(tree)).toContain('NVIDIA');
    expect(flattenText(tree)).toContain('AMD');
    expect(flattenText(tree)).toContain('光子芯片技术');
    expect(flattenText(tree)).toContain('存算一体架构');
    expect(flattenText(tree)).toContain('01. IEA 半导体与算力追踪报告 2024');

    const heading = collectElements(
      tree,
      (element) =>
        element.type === Typography &&
        flattenText(element.props.children) === '全球人工智能半导体行业：2024年深度分析报告'
    )[0];
    expect(heading?.props.variant).toBe('h2');
  });
});

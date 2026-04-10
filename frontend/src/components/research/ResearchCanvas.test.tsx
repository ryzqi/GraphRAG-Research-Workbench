import { Paper, Typography } from '@mui/material';
import { isValidElement, type ComponentProps, type ReactElement, type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { ResearchCanvas } from './ResearchCanvas';
import { ResearchShell } from './ResearchShell';

type ResearchShellProps = ComponentProps<typeof ResearchShell>;

function collectElements(
  node: ReactNode,
  predicate: (
    element: ReactElement<{ children?: ReactNode; sx?: unknown; variant?: string; tone?: string }>
  ) => boolean
): ReactElement<{ children?: ReactNode; sx?: unknown; variant?: string; tone?: string }>[] {
  const matches: ReactElement<{ children?: ReactNode; sx?: unknown; variant?: string; tone?: string }>[] = [];

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
      tone?: string;
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

describe('ResearchCanvas', () => {
  it('renders the live research dashboard with progress and activity cards', () => {
    const tree = ResearchCanvas({
      model: {
        surface: 'live',
        hero: {
          eyebrow: 'Deep Research',
          title: '2024年全球电动汽车市场格局与补贴政策深度分析报告',
          subtitle: '正在整合来自全球 50+ 权威数据源的研究线索。',
        },
        railSteps: [
          { key: 'clarify', label: '澄清问题', state: 'complete' },
          { key: 'plan', label: '研究计划', state: 'complete' },
          { key: 'run', label: '执行研究', state: 'current' },
        ],
        live: {
          progress: {
            label: '研究执行中',
            percent: 68,
            currentStageLabel: '语义建模',
          },
          currentAgentLabel: 'web',
          currentTaskLabel: '验证 claim 1 的网页证据',
          currentTaskKind: 'claim',
          parallelTasks: [
            {
              id: 'claim-1-web',
              label: '验证 claim 1 的网页证据',
              taskKind: 'claim',
              status: 'started',
              agentLabel: 'web',
              parallelGroup: 'claim-1',
            },
          ],
          planSteps: [
            { key: 'plan-step-1', label: '数据收集', state: 'complete' },
            { key: 'plan-step-2', label: '特征提取', state: 'complete' },
            { key: 'plan-step-3', label: '语义建模', state: 'current' },
            { key: 'plan-step-4', label: '结论生成', state: 'pending' },
          ],
          coverageLabel: '已汇总 12 条引用',
          activity: [
            {
              id: 'a-1',
              eventType: 'research.trace.recorded',
              title: '记录来源轨迹：searxng',
              body: '最近活跃链路：searxng / web-search',
              phase: 'runtime',
            },
          ],
          timelineItems: [],
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
    });

    expect(flattenText(tree)).toContain('研究进度实时追踪');
    expect(flattenText(tree)).toContain('68%');
    expect(flattenText(tree)).toContain('当前计划步骤：语义建模');
    expect(flattenText(tree)).toContain('当前代理：web');
    expect(flattenText(tree)).toContain('当前任务：验证 claim 1 的网页证据');
    expect(flattenText(tree)).toContain('并行任务');
    expect(flattenText(tree)).toContain('系统运行正常，已汇总 12 条引用');
    expect(flattenText(tree)).toContain('数据收集');
    expect(flattenText(tree)).toContain('特征提取');
    expect(flattenText(tree)).toContain('语义建模');
    expect(flattenText(tree)).toContain('结论生成');
    expect(flattenText(tree)).not.toContain('web运行中0/1');
    expect(flattenText(tree)).toContain('记录来源轨迹：searxng');
    expect(flattenText(tree)).not.toContain('来源与证据');
    expect(flattenText(tree)).not.toContain('研究时间流');
    expect(flattenText(tree)).not.toContain('LIVE');
    expect(flattenText(tree)).not.toContain('Just now');
    expect(flattenText(tree)).not.toContain('ago');

    const headerLabel = collectElements(
      tree,
      (element) =>
        element.type === Typography &&
        flattenText(element.props.children) === '2024年全球电动汽车市场格局与补贴政策深度分析报告'
    )[0];
    expect(headerLabel?.props.variant).toBe('h2');

    const paperCards = collectElements(
      tree,
      (element) => element.type === Paper
    );
    expect(paperCards.length).toBeGreaterThan(0);
  });
});

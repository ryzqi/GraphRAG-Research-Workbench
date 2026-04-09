import { Paper, Typography } from '@mui/material';
import { isValidElement, type ComponentProps, type ReactElement, type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { ResearchCanvas } from './ResearchCanvas';
import { ResearchEvidenceLedger } from './ResearchEvidenceLedger';
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
            currentStageLabel: '执行研究',
          },
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

    expect(flattenText(tree)).toContain('研究执行中');
    expect(flattenText(tree)).toContain('阶段 03');
    expect(flattenText(tree)).toContain('进度跟踪');
    expect(flattenText(tree)).toContain('总体进度 68%');
    expect(flattenText(tree)).toContain('运行状态');
    expect(flattenText(tree)).toContain('记录来源轨迹：searxng');

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

    const evidenceLedger = collectElements(
      tree,
      (element) => element.type === ResearchEvidenceLedger
    )[0];
    expect(evidenceLedger).toBeDefined();
  });
});

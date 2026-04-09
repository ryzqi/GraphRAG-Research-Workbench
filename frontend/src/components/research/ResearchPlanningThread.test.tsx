import { Typography } from '@mui/material';
import { isValidElement, type ComponentProps, type ReactElement, type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { ResearchPlanningThread } from './ResearchPlanningThread';
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

describe('ResearchPlanningThread', () => {
  it('renders clarification cards and known context from the new planning shell', () => {
    const tree = ResearchPlanningThread({
      model: {
        surface: 'clarifying',
        hero: {
          eyebrow: 'Deep Research',
          title: '2024年全球电动汽车市场分析',
          subtitle: '为了生成更精确的报告，需要先补齐研究边界。',
        },
        railSteps: [
          { key: 'clarify', label: '澄清问题', state: 'current' },
          { key: 'plan', label: '研究计划', state: 'pending' },
        ],
        clarification: {
          summary: '为了生成更精确的报告，需要先补齐研究边界。',
          knownContext: '当前已收到的研究问题是：2024年全球电动汽车市场分析',
          inputPlaceholder: '回复以上问题以优化研究路径…',
          submitLabel: '提交补充信息',
          questionCards: [
            {
              id: 'region',
              title: '更关注哪些地区？',
              description: '地区范围会直接改变样本和政策比较维度。',
            },
            {
              id: 'policy',
              title: '是否重点关注补贴政策？',
              description: '这会影响研究重点和指标选择。',
            },
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
      clarificationDraft: '',
    });

    expect(flattenText(tree)).toContain('阶段 01');
    expect(flattenText(tree)).toContain('澄清问题');
    expect(flattenText(tree)).toContain('待确认的研究维度');
    expect(flattenText(tree)).toContain('更关注哪些地区？');
    expect(flattenText(tree)).toContain('研究输入摘要');
    expect(flattenText(tree)).toContain('提交补充信息');
  });

  it('renders numbered plan steps and dual actions for plan_ready', () => {
    const tree = ResearchPlanningThread({
      model: {
        surface: 'planning',
        hero: {
          eyebrow: 'Deep Research',
          title: '2024年全球电动汽车市场分析',
          subtitle: '研究计划已生成，可继续调整后开始执行。',
        },
        railSteps: [
          { key: 'clarify', label: '澄清问题', state: 'complete' },
          { key: 'plan', label: '研究计划', state: 'current' },
        ],
        plan: {
          researchBrief: '聚焦欧洲与中国新能源汽车市场竞争格局。',
          summary: '比较主要市场、政策补贴和代表企业走势。',
          steps: [
            {
              index: 1,
              title: '收集市场规模与销量数据',
              description: '整理 2024 年主要地区销量、渗透率和增长率。',
              targetSources: ['网页', '知识库'],
            },
          ],
          secondaryActionLabel: '更新计划',
          primaryActionLabel: '开始研究',
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
      planFeedbackDraft: '',
    });

    expect(flattenText(tree)).toContain('阶段 02');
    expect(flattenText(tree)).toContain('研究计划');
    expect(flattenText(tree)).toContain('拟定研究计划');
    expect(flattenText(tree)).toContain('收集市场规模与销量数据');
    expect(flattenText(tree)).toContain('来源焦点');
    expect(flattenText(tree)).toContain('网页');
    expect(flattenText(tree)).toContain('知识库');
    expect(flattenText(tree)).toContain('更新计划');
    expect(flattenText(tree)).toContain('开始研究');

    const descriptionBlock = collectElements(
      tree,
      (element) =>
        element.type === Typography &&
        flattenText(element.props.children) === '整理 2024 年主要地区销量、渗透率和增长率。'
    )[0];
    expect(descriptionBlock?.props.sx).toEqual(
      expect.objectContaining({
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        overflowWrap: 'anywhere',
      })
    );
  });
});

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
              title: '您更关注哪些特定地区？',
              description: '全球汇总，还是专注于中国、欧盟或北美等主要增长引擎？',
            },
            {
              id: 'policy',
              title: '是否侧重于政策与补贴的影响？',
              description: '例如美国 IRA 法案或欧盟反补贴调查对 2024 年市场份额的潜在重塑。',
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

    expect(flattenText(tree)).toContain('待确认的研究维度');
    expect(flattenText(tree)).toContain('您更关注哪些特定地区？');
    expect(flattenText(tree)).toContain('当前的初步认知');
    expect(flattenText(tree)).toContain('提交补充信息');
    expect(flattenText(tree)).not.toContain('研究输入摘要');
    expect(flattenText(tree)).not.toContain('本轮将影响');
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
              title: '搜集主流市场数据',
              description: '我们将通过检索国际能源署（IEA）和彭博新能源财经（BNEF）的最新报告，汇总 2024 年太阳能、风能及储能领域的容量增长与投资分布数据。',
              targetSources: ['网页', '知识库'],
            },
          ],
          secondaryActionLabel: '修改计划',
          primaryActionLabel: '开始深度研究',
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

    expect(flattenText(tree)).toContain('研究计划');
    expect(flattenText(tree)).toContain('拟定研究计划');
    expect(flattenText(tree)).toContain('研究步骤详细方案');
    expect(flattenText(tree)).toContain('搜集主流市场数据');
    expect(flattenText(tree)).toContain('网页');
    expect(flattenText(tree)).toContain('知识库');
    expect(flattenText(tree)).toContain('修改计划');
    expect(flattenText(tree)).toContain('开始深度研究');
    expect(flattenText(tree)).not.toContain('来源焦点');
    expect(flattenText(tree)).not.toContain('执行约束');

    const descriptionBlock = collectElements(
      tree,
      (element) =>
        element.type === Typography &&
        flattenText(element.props.children) ===
          '我们将通过检索国际能源署（IEA）和彭博新能源财经（BNEF）的最新报告，汇总 2024 年太阳能、风能及储能领域的容量增长与投资分布数据。'
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

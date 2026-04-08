import { Paper, Typography } from '@mui/material';
import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { ResearchPlanningThread } from './ResearchPlanningThread';
import type { ResearchPlanSnapshot } from '../../types/researchEvents';

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

  return flattenText((node as ReactElement<{ children?: ReactNode }>).props.children);
}

describe('ResearchPlanningThread', () => {
  it('uses the workbench summary card while keeping long text safe', () => {
    const planSnapshot: ResearchPlanSnapshot = {
      research_brief: 'brief',
      complexity: 'complex',
      summary:
        '已知焦点为RAG（检索增强生成）技术的最新进展。时间范围采用默认保守假设，聚焦2024-2025年公开可核查的主流进展，并输出面向技术从业者的结构化摘要。',
      target_sources: ['web', 'paper'],
      subtasks: [
        {
          title: '主流技术路线与核心论文收集',
          description:
            '系统收集2024-2025年RAG领域代表性论文、开源项目与技术博客，按检索优化、上下文处理、多模态扩展、架构创新等维度归类，提取方法要点与宣称的性能指标。',
          target_sources: ['web', 'paper'],
        },
      ],
    };

    const tree = ResearchPlanningThread({
      question: '当前RAG的最新进展',
      status: 'plan_ready',
      planSnapshot,
      planFeedbackDraft: '',
    });

    const paperCards = collectElements(
      tree,
      (element) => element.type === Paper && element.props.variant === 'outlined'
    );
    expect(paperCards[0]?.props.sx).toEqual(
      expect.objectContaining({ borderRadius: 24, overflow: 'hidden' })
    );
    expect(flattenText(tree)).toContain('研究问题');
    expect(flattenText(tree)).toContain('研究计划');

    const summaryBlock = collectElements(
      tree,
      (element) =>
        element.type === Typography && flattenText(element.props.children) === planSnapshot.summary
    )[0];
    expect(summaryBlock?.props.sx).toEqual(
      expect.objectContaining({
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        overflowWrap: 'anywhere',
      })
    );

    const descriptionBlock = collectElements(
      tree,
      (element) =>
        element.type === Typography &&
        flattenText(element.props.children) === planSnapshot.subtasks[0]?.description
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

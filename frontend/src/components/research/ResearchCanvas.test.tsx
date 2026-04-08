import { Paper, Typography } from '@mui/material';
import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { ResearchCanvas } from './ResearchCanvas';

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

describe('ResearchCanvas', () => {
  it('uses the new workbench header and rounded card system', () => {
    const tree = ResearchCanvas({
      model: {
        surface: 'live-research',
        title: '测试研究任务',
        statusLabel: '研究中…',
        statusTone: 'running',
        coverageLabel: '已覆盖 2 个来源',
        timelineItems: [],
        evidenceDrawer: {
          contractErrors: [],
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
      exportButton: null,
      actions: null,
    });

    expect(flattenText(tree)).toContain('Research Workbench');

    const headerLabel = collectElements(
      tree,
      (element) =>
        element.type === Typography && flattenText(element.props.children) === 'Research Workbench'
    )[0];
    expect(headerLabel?.props.variant).toBe('overline');

    const paperCards = collectElements(
      tree,
      (element) => element.type === Paper && element.props.variant === 'outlined'
    );
    expect(paperCards[0]?.props.sx).toEqual(expect.objectContaining({ borderRadius: 24 }));
  });
});

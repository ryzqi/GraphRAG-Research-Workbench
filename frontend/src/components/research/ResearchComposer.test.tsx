import { Paper, Typography } from '@mui/material';
import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { ResearchComposer } from './ResearchComposer';

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

describe('ResearchComposer', () => {
  it('renders the new workbench heading and intro copy', () => {
    const tree = ResearchComposer({
      question: '',
      loading: false,
      validationError: null,
      onQuestionChange: () => undefined,
      onStart: () => undefined,
    });

    expect(flattenText(tree)).toContain('深度研究工作台');
    expect(flattenText(tree)).toContain('把问题拆成计划、证据和最终结论');

    const introHeading = collectElements(
      tree,
      (element) =>
        element.type === Typography && flattenText(element.props.children) === '深度研究工作台'
    )[0];
    expect(introHeading?.props.variant).toBe('h3');

    const composerCard = collectElements(
      tree,
      (element) => element.type === Paper && element.props.variant === 'outlined'
    )[0];
    expect(composerCard?.props.sx).toEqual(expect.objectContaining({ borderRadius: 24 }));
  });
});

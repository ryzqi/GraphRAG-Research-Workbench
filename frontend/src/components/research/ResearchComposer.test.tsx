import { InputBase, Paper, Typography } from '@mui/material';
import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { ResearchComposer } from './ResearchComposer';

interface TestElementProps {
  children?: ReactNode;
  sx?: unknown;
  variant?: string;
  id?: string;
  multiline?: boolean;
  minRows?: number;
  maxRows?: number;
  placeholder?: string;
}

function collectElements(
  node: ReactNode,
  predicate: (element: ReactElement<TestElementProps>) => boolean
): ReactElement<TestElementProps>[] {
  const matches: ReactElement<TestElementProps>[] = [];

  const visit = (current: ReactNode): void => {
    if (Array.isArray(current)) {
      current.forEach(visit);
      return;
    }

    if (!isValidElement(current)) {
      return;
    }

    const element = current as ReactElement<TestElementProps>;
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
  it('renders a minimal centered hero with a compact research search shell', () => {
    const tree = ResearchComposer({
      question: '',
      loading: false,
      validationError: null,
      onQuestionChange: () => undefined,
      onStart: () => undefined,
    });

    expect(flattenText(tree)).toContain('深度研究');
    expect(flattenText(tree)).toContain('开启研究');
    expect(flattenText(tree)).not.toContain('边界先澄清');
    expect(flattenText(tree)).not.toContain('计划后执行');
    expect(flattenText(tree)).not.toContain('证据可追溯');

    const introHeading = collectElements(
      tree,
      (element) => element.type === Typography && flattenText(element.props.children) === '深度研究'
    )[0];
    expect(introHeading?.props.variant).toBe('h1');

    const searchShell = collectElements(
      tree,
      (element) => element.type === Paper && element.props.variant === 'outlined'
    )[0];
    expect(searchShell?.props.sx).toEqual(
      expect.objectContaining({
        borderRadius: 999,
        maxWidth: 860,
      })
    );

    const centeredShell = collectElements(
      tree,
      (element) => element.type === Paper && element.props.variant === 'outlined'
    )[0];
    expect(centeredShell?.props.sx).toEqual(
      expect.objectContaining({
        mx: 'auto',
      })
    );

    const questionInput = collectElements(
      tree,
      (element) => element.type === InputBase && element.props.id === 'research-question-input'
    )[0];
    expect(questionInput?.props.multiline).toBe(true);
    expect(questionInput?.props.minRows).toBe(1);
    expect(questionInput?.props.maxRows).toBe(3);
    expect(questionInput?.props.placeholder).toBe('输入您想要深度研究的主题或问题...');
  });
});

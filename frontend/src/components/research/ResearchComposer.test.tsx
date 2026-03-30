import type { ComponentProps } from 'react';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchComposer } from './ResearchComposer';

describe('ResearchComposer', () => {
  it('renders the new planning hero without the confirmation switch', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchComposer, {
        question: '比较两种方案',
        loading: false,
        validationError: null,
        onQuestionChange: () => undefined,
        onStart: () => undefined,
      })
    );

    expect(html).toContain('先规划，再开始研究');
    expect(html).toContain('研究会先收敛问题，再进入正式执行');
    expect(html).toContain('生成研究计划');
    expect(html).not.toContain('执行前确认计划');
  });

  it('does not accept legacy confirmation toggle props', () => {
    const props: ComponentProps<typeof ResearchComposer> = {
      question: '比较两种方案',
      loading: false,
      validationError: null,
      onQuestionChange: () => undefined,
      onStart: () => undefined,
      // @ts-expect-error Task 3 removes the legacy toggle contract
      requireConfirmation: true,
      // @ts-expect-error Task 3 removes the legacy toggle contract
      onToggleRequireConfirmation: () => undefined,
    };

    expect(props.question).toBe('比较两种方案');
  });
});

import type { ComponentProps } from 'react';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, expectTypeOf, it } from 'vitest';

import { ResearchComposer } from './ResearchComposer';

describe('ResearchComposer', () => {
  it('renders a Google-like minimal entry without the old center hero copy', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchComposer, {
        question: '比较两种方案',
        loading: false,
        validationError: null,
        onQuestionChange: () => undefined,
        onStart: () => undefined,
      })
    );

    expect(html).toContain('有问题，尽管问');
    expect(html).toContain('开始研究');
    expect(html).not.toContain('先规划，再开始研究');
    expect(html).not.toContain('研究会先收敛问题，再进入正式执行');
    expect(html).not.toContain('执行前确认计划');
  });

  it('does not accept legacy confirmation toggle props', () => {
    type ComposerProps = ComponentProps<typeof ResearchComposer>;

    expectTypeOf<ComposerProps>().not.toHaveProperty('requireConfirmation');
    expectTypeOf<ComposerProps>().not.toHaveProperty('onToggleRequireConfirmation');
  });
});

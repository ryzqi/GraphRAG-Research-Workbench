import type { ComponentProps } from 'react';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, expectTypeOf, it } from 'vitest';

import { ResearchComposer } from './ResearchComposer';

describe('ResearchComposer', () => {
  it('renders only the minimal entry controls without static hero copy', () => {
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
    expect(html).not.toContain('Deep Research');
    expect(html).not.toContain('用研究工作台，把问题拆清、证据拉齐、报告收口');
    expect(html).not.toContain(
      '对齐 Gemini 风格的轻量研究入口：先聚焦问题，再进入规划、执行与最终报告。'
    );
    expect(html).not.toContain('先规划，再开始研究');
    expect(html).not.toContain('研究会先收敛问题，再进入正式执行');
    expect(html).not.toContain('执行前确认计划');
    expect(html).not.toContain('linear-gradient(180deg,#f8fbff 0%,#eef4ff 48%,#f8fbff 100%)');
    expect(html).not.toContain('max-width:880px');
  });

  it('does not accept legacy confirmation toggle props', () => {
    type ComposerProps = ComponentProps<typeof ResearchComposer>;

    expectTypeOf<ComposerProps>().not.toHaveProperty('requireConfirmation');
    expectTypeOf<ComposerProps>().not.toHaveProperty('onToggleRequireConfirmation');
  });
});

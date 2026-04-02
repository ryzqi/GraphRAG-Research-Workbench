import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { MarkdownContent } from './MarkdownContent';

describe('MarkdownContent', () => {
  it('renders mermaid fenced blocks through a dedicated diagram container', () => {
    const html = renderToStaticMarkup(
      createElement(MarkdownContent, {
        content: '```mermaid\ngraph TD\nA[Plan] --> B[Run]\n```',
      })
    );

    expect(html).toContain('data-mermaid-diagram="true"');
    expect(html).toContain('graph TD');
    expect(html).toContain('A[Plan] --&gt; B[Run]');
  });
});

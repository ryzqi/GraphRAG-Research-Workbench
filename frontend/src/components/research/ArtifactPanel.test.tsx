import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ArtifactPanel } from './ArtifactPanel';

describe('ArtifactPanel', () => {
  it('renders markdown, json, intermediate artifacts, and differentiates web/paper citations safely', () => {
    const html = renderToStaticMarkup(
      createElement(ArtifactPanel, {
        reportMd: '# 报告\n\n<script>alert(1)</script>\n最终结论',
        reportJson: {
          citations: [
            {
              source_type: 'web',
              source_provider: 'jina_reader',
              retrieval_method: 'read',
              source_id: 'web-1',
              title: '网页来源',
              origin_url: 'https://origin.example.com/a',
              authors: [],
            },
            {
              source_type: 'paper',
              source_provider: 'arxiv',
              retrieval_method: 'fetch',
              source_id: 'paper-1',
              title: 'Paper Source',
              authors: ['Alice'],
              published_at: '2026-03-30T00:00:00Z',
              arxiv_id: '2503.00001',
              pdf_url: 'https://arxiv.org/pdf/2503.00001.pdf',
            },
          ],
        },
        artifacts: [
          {
            artifact_key: 'interim_summary',
            content_text: '已完成第一次来源收口',
            citations: [],
          },
          {
            artifact_key: 'coverage_gaps',
            content_json: ['缺少最新实施细则'],
            citations: [],
          },
        ],
      })
    );

    expect(html).toContain('研究工件');
    expect(html).toContain('中间研究收口');
    expect(html).toContain('网页证据');
    expect(html).toContain('论文证据');
    expect(html).toContain('https://origin.example.com/a');
    expect(html).toContain('2503.00001');
    expect(html).toContain('PDF');
    expect(html).not.toContain('<script>');
  });
});

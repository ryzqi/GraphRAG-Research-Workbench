import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { EvidenceList } from './EvidenceList';

describe('EvidenceList', () => {
  it('renders citation source cards instead of accordion summaries', () => {
    const html = renderToStaticMarkup(
      createElement(EvidenceList, {
        citationAnchorScopeId: 'assistant-msg-1',
        evidence: [
          {
            source_kind: 'kb',
            kb_id: null,
            material_id: null,
            chunk_id: null,
            locator: {
              material_title: '产品发布说明',
              filename: 'docs/product-launch.pdf',
              page_start: 5,
            },
            excerpt: '新版本将于四月上线。',
            source_excerpt: '新版本将于四月上线，并默认开启知识库引用卡片。',
            citation_id: 'S1',
            citation_title: '产品发布说明 V2',
            citation_page_hint: 'p.5',
            citation_source: 'docs/product-launch.pdf',
          },
        ],
      })
    );

    expect(html).toContain('参考来源');
    expect(html).toContain('data-citation-card="S1"');
    expect(html).toContain('data-citation-anchor="cite-assistant-msg-1-S1"');
    expect(html).toContain('产品发布说明 V2');
    expect(html).toContain('docs/product-launch.pdf');
    expect(html).toContain('知识库文档');
    expect(html).toContain('p.5');
    expect(html).toContain('新版本将于四月上线，并默认开启知识库引用卡片。');
  });

  it('marks the active citation card for highlight styling', () => {
    const html = renderToStaticMarkup(
      createElement(EvidenceList, {
        activeCitationId: 's2',
        evidence: [
          {
            source_kind: 'kb',
            kb_id: null,
            material_id: null,
            chunk_id: null,
            locator: { material_title: '文档一' },
            excerpt: '片段一',
            citation_id: 'S1',
          },
          {
            source_kind: 'external',
            kb_id: null,
            material_id: null,
            chunk_id: null,
            locator: { material_title: '文档二' },
            excerpt: '片段二',
            citation_id: 'S2',
          },
        ],
      })
    );

    expect(html).toContain('data-citation-card="S2"');
    expect(html).toContain('data-active="true"');
  });
});

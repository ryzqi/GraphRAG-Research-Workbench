import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchCanvas } from './ResearchCanvas';

describe('ResearchCanvas', () => {
  it('renders an immersive research stream with timeline cards and evidence drawer', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchCanvas, {
        model: {
          surface: 'live-research',
          title: '比较调度路线',
          statusLabel: '研究中…',
          statusTone: 'running',
          coverageLabel: '已覆盖 2 个来源 / 1 个缺口',
          timelineItems: [
            {
              id: 'evt-1',
              kind: 'web_visit',
              title: '访问 example.com',
              body: '已抓取关键页面段落',
              phaseLabel: 'retrieval',
              providerLabel: 'searxng',
              url: 'https://example.com/a',
            },
            {
              id: 'evt-2',
              kind: 'thought_summary',
              title: '正在比较两条路线的稳定性',
              body: '先对齐公开网页证据，再补充覆盖缺口。',
              phaseLabel: 'analysis',
              providerLabel: null,
              url: null,
            },
          ],
          evidenceDrawer: {
            contractErrors: [],
            coverageGap: '仍需补充一条公开网页案例。',
            coverageMarkdown: null,
            coverageMatrix: {
              provider_counts: { searxng: 2 },
              missing_providers: ['tavily'],
            },
            sources: [
              {
                provider: 'searxng',
                title: '路线对比',
                origin_url: 'https://example.com/a',
                source_type: 'web',
              },
            ],
            claims: [],
            conflicts: [],
          },
        },
        exportButton: null,
        actions: createElement('button', null, '新研究'),
      })
    );

    expect(html).toContain('比较调度路线');
    expect(html).toContain('研究时间流');
    expect(html).toContain('网页访问');
    expect(html).toContain('摘要思考');
    expect(html).toContain('访问 example.com');
    expect(html).toContain('查看来源与证据');
    expect(html).toContain('仍需补充一条公开网页案例');
    expect(html).not.toContain('linear-gradient(180deg,#f7faff 0%,#eef4ff 45%,#f8fbff 100%)');
    expect(html).not.toContain('radial-gradient(circle at top,rgba(66,133,244,0.18) 0%,rgba(66,133,244,0) 42%)');
    expect(html).not.toContain('max-width:1040px');
    expect(html).not.toContain('live research');
    expect(html).not.toContain('deep research stream');
    expect(html).not.toContain('source trace');
    expect(html).not.toContain('thinking');
    expect(html).not.toContain('working answer');
    expect(html).not.toContain('session state');
    expect(html).not.toContain('高级事件');
  });

  it('shows a pure report page when final report exists', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchCanvas, {
        model: {
          surface: 'final-report',
          title: '比较调度路线',
          statusLabel: '已完成',
          statusTone: 'succeeded',
          coverageLabel: '已覆盖 2 个来源',
          timelineItems: [],
          report: {
            markdown: '# 最终报告\n\n结论正文',
          },
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
        exportButton: createElement('button', null, '导出报告'),
        actions: null,
      })
    );

    expect(html).toContain('最终报告');
    expect(html).toContain('导出报告');
    expect(html).toContain('结论正文');
    expect(html).toContain('linear-gradient(180deg,rgba(255,255,255,0.98) 0%,rgba(245,249,255,0.98) 100%)');
    expect(html).not.toContain('max-width:1040px');
    expect(html).not.toContain('final report');
    expect(html).not.toContain('研究时间流');
  });
});

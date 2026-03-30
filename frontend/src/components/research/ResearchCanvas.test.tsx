import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchCanvas } from './ResearchCanvas';

describe('ResearchCanvas', () => {
  it('shows progressive sections while the final report is not ready', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchCanvas, {
        model: {
          mode: 'progressive',
          currentStepTitle: '当前正在做什么',
          currentStepBody: '正在补充网页证据。',
          findingsTitle: '阶段性发现',
          findingsBody: '两条路线在稳定性上差异明显。',
          finalReportTitle: '最终报告',
          finalReportBody: null,
          coverageGap: '仍需补充一条知识库案例。',
        },
        artifactPanel: createElement('div', null, '证据面板'),
        exportButton: null,
      })
    );

    expect(html).toContain('当前正在做什么');
    expect(html).toContain('阶段性发现');
    expect(html).toContain('仍需补充一条知识库案例');
    expect(html).not.toContain('导出报告');
  });

  it('shows report-first reading mode when final report exists', () => {
    const html = renderToStaticMarkup(
      createElement(ResearchCanvas, {
        model: {
          mode: 'final',
          currentStepTitle: '当前正在做什么',
          currentStepBody: '研究已完成。',
          findingsTitle: '阶段性发现',
          findingsBody: '阶段摘要',
          finalReportTitle: '最终报告',
          finalReportBody: '# 最终报告\n\n结论正文',
          coverageGap: null,
        },
        artifactPanel: createElement('div', null, '证据面板'),
        exportButton: createElement('button', null, '导出报告'),
      })
    );

    expect(html).toContain('最终报告');
    expect(html).toContain('导出报告');
    expect(html).toContain('结论正文');
  });
});

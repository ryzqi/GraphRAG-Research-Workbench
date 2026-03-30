import { describe, expect, it } from 'vitest';

import {
  buildResearchCanvasModel,
  buildResearchProgressFeed,
  buildResearchSourceSummary,
} from './researchWorkbench';
import type { ResearchArtifactRead, ResearchEventEnvelope } from '../types/researchEvents';

const runningEvents: ResearchEventEnvelope[] = [
  {
    event_id: 'evt-2',
    sequence: 2,
    timestamp: '2026-03-30T10:00:02Z',
    event_type: 'research.run.started',
    session_id: 'session-1',
    phase: 'runtime',
    namespace: 'main',
    payload: { summary: '开始调度研究' },
    source_provider: 'tavily',
    retrieval_method: 'search',
  },
  {
    event_id: 'evt-3',
    sequence: 3,
    timestamp: '2026-03-30T10:00:03Z',
    event_type: 'research.trace.recorded',
    session_id: 'session-1',
    phase: 'retrieval',
    namespace: 'main',
    payload: { summary: '抓取到两篇网页证据', finding: '两条路线在时效性上差异明显' },
    source_provider: 'searxng',
    retrieval_method: 'search',
    origin_url: 'https://example.com/a',
  },
];

const interimArtifacts: ResearchArtifactRead[] = [
  {
    artifact_key: 'interim_summary',
    content_text: '当前已完成路线比较，并进入证据补充阶段。',
    citations: [],
  },
  {
    artifact_key: 'coverage_gaps',
    content_text: '仍需补充一条公开网页案例。',
    citations: [],
  },
];

describe('buildResearchSourceSummary', () => {
  it('returns network-only source summary', () => {
    expect(buildResearchSourceSummary()).toEqual({
      heading: '研究来源',
      modeLabel: '网络搜索深度研究',
      helperText: '当前仅使用联网检索与外部资料完成研究。',
    });
  });
});

describe('buildResearchCanvasModel', () => {
  it('shows progressive sections before report_md exists', () => {
    expect(
      buildResearchCanvasModel({
        status: 'running',
        events: runningEvents,
        artifacts: interimArtifacts,
        reportMd: null,
      })
    ).toMatchObject({
      mode: 'progressive',
      currentStepTitle: '当前正在做什么',
      findingsTitle: '阶段性发现',
      finalReportTitle: '最终报告',
      finalReportBody: null,
    });
  });

  it('promotes report_md to the primary reading surface after finalization', () => {
    expect(
      buildResearchCanvasModel({
        status: 'final',
        events: runningEvents,
        artifacts: interimArtifacts,
        reportMd: '# 最终报告\n\n结论正文',
      }).mode
    ).toBe('final');
  });
});

describe('buildResearchProgressFeed', () => {
  it('returns human-readable progress items instead of raw event metadata', () => {
    expect(buildResearchProgressFeed(runningEvents)[0]).toMatchObject({
      title: '抓取到两篇网页证据',
      phaseLabel: 'retrieval',
      providerLabel: 'searxng',
    });
  });
});

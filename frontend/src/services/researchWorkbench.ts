import type {
  ResearchArtifactRead,
  ResearchEventEnvelope,
  ResearchSessionStatus,
} from '../types/researchEvents';

export interface ResearchProgressFeedItem {
  id: string;
  title: string;
  phaseLabel: string;
  providerLabel: string | null;
  sourceLabel: string | null;
  finding: string | null;
}

interface ResearchArtifactSummary {
  interimSummary: string | null;
  coverageGap: string | null;
}

export function buildResearchSourceSummary() {
  return {
    heading: '研究来源',
    modeLabel: '网络搜索深度研究',
    helperText: '当前仅使用联网检索与外部资料完成研究。',
  };
}

function summarizeResearchArtifacts(artifacts: ResearchArtifactRead[]): ResearchArtifactSummary {
  let interimSummary: string | null = null;
  let coverageGap: string | null = null;

  for (const artifact of artifacts) {
    if (artifact.artifact_key === 'interim_summary' && interimSummary === null) {
      interimSummary = artifact.content_text ?? null;
      continue;
    }
    if (artifact.artifact_key === 'coverage_gaps' && coverageGap === null) {
      coverageGap = artifact.content_text ?? null;
    }
  }

  return {
    interimSummary,
    coverageGap,
  };
}

export function buildResearchProgressFeed(events: ResearchEventEnvelope[]): ResearchProgressFeedItem[] {
  return [...events]
    .sort((left, right) => right.sequence - left.sequence)
    .map((event) => ({
      id: event.event_id,
      title:
        typeof event.payload.summary === 'string' && event.payload.summary.trim().length > 0
          ? event.payload.summary
          : event.event_type,
      phaseLabel: event.phase,
      providerLabel: event.source_provider ?? null,
      sourceLabel: event.origin_url ?? null,
      finding:
        typeof event.payload.finding === 'string' && event.payload.finding.trim().length > 0
          ? event.payload.finding
          : null,
    }));
}

export function buildResearchCanvasModel(params: {
  status: ResearchSessionStatus;
  events: ResearchEventEnvelope[];
  artifacts: ResearchArtifactRead[];
  reportMd: string | null;
  progressFeed?: ResearchProgressFeedItem[];
}): {
  mode: 'final' | 'progressive';
  currentStepTitle: string;
  currentStepBody: string;
  findingsTitle: string;
  findingsBody: string | null;
  finalReportTitle: string;
  finalReportBody: string | null;
  coverageGap: string | null;
} {
  const { interimSummary, coverageGap } = summarizeResearchArtifacts(params.artifacts);
  const progressFeed = params.progressFeed ?? buildResearchProgressFeed(params.events);

  return {
    mode: params.reportMd ? 'final' : 'progressive',
    currentStepTitle: '当前正在做什么',
    currentStepBody: progressFeed[0]?.title ?? '等待研究启动。',
    findingsTitle: '阶段性发现',
    findingsBody: interimSummary,
    finalReportTitle: '最终报告',
    finalReportBody: params.reportMd,
    coverageGap,
  };
}

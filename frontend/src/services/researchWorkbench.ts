import type {
  ResearchArtifactRead,
  ResearchClaimMapEntry,
  ResearchClaimVerdict,
  ResearchConflictEntry,
  ResearchCoverageMatrix,
  ResearchEventEnvelope,
  ResearchSessionStatus,
  ResearchSourceLedgerEntry,
  ResearchSourceType,
} from '../types/researchEvents';

import { buildResearchArtifactsByKey, getResearchReportArtifacts } from '../types/researchEvents';

interface ResearchArtifactSummary {
  interimSummary: string | null;
  coverageGap: string | null;
}

export interface ResearchWorkspaceModel {
  contractErrors: string[];
  mission: {
    markdown: string | null;
  };
  plan: {
    markdown: string | null;
    subtaskCount: number;
  };
  coverage: {
    markdown: string | null;
    matrix: ResearchCoverageMatrix;
  };
  evidence: {
    sources: ResearchSourceLedgerEntry[];
    conflicts: ResearchConflictEntry[];
  };
  claims: {
    items: ResearchClaimMapEntry[];
  };
  report: {
    markdown: string | null;
    json: Record<string, unknown> | null;
  };
}

export interface ResearchTimelineItem {
  id: string;
  kind: 'web_visit' | 'thought_summary' | 'intermediate_result' | 'system_status';
  title: string;
  body: string | null;
  phaseLabel: string;
  providerLabel: string | null;
  url: string | null;
}

export interface ResearchEvidenceDrawerModel {
  contractErrors: string[];
  coverageGap: string | null;
  coverageMarkdown: string | null;
  coverageMatrix: ResearchCoverageMatrix;
  sources: ResearchSourceLedgerEntry[];
  claims: ResearchClaimMapEntry[];
  conflicts: ResearchConflictEntry[];
}

export interface ResearchPageViewModel {
  surface: 'live-research' | 'final-report';
  timelineItems: ResearchTimelineItem[];
  evidenceDrawer: ResearchEvidenceDrawerModel;
  report?: {
    markdown: string;
  };
}

const DEFAULT_RESEARCH_COVERAGE_MATRIX: ResearchCoverageMatrix = {
  provider_counts: {},
  missing_providers: [],
};

function pushContractError(
  contractErrors: string[],
  artifactKey: string,
  expected: '数组' | '对象'
) {
  contractErrors.push(`${artifactKey} 格式无效：期望${expected}`);
}

function readArtifactMarkdown(artifact: ResearchArtifactRead | undefined): string | null {
  return typeof artifact?.content_text === 'string' && artifact.content_text.trim().length > 0
    ? artifact.content_text
    : null;
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    .map((item) => item.trim());
}

function asCitationIndices(value: unknown): number[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (index: unknown): index is number => typeof index === 'number' && Number.isInteger(index)
  );
}

function readCoverageGap(artifact: ResearchArtifactRead | undefined): string | null {
  const contentJsonItems = asStringList(artifact?.content_json);
  if (contentJsonItems.length > 0) {
    return contentJsonItems.join('\n');
  }
  return readArtifactMarkdown(artifact);
}

function asCoverageMatrix(
  artifact: ResearchArtifactRead | undefined,
  contractErrors: string[]
): ResearchCoverageMatrix {
  const value = artifact?.content_json;
  if (artifact && (!value || Array.isArray(value) || typeof value !== 'object')) {
    pushContractError(contractErrors, artifact.artifact_key, '对象');
    return { ...DEFAULT_RESEARCH_COVERAGE_MATRIX };
  }
  if (!value || Array.isArray(value) || typeof value !== 'object') {
    return { ...DEFAULT_RESEARCH_COVERAGE_MATRIX };
  }

  const rawProviderCounts =
    'provider_counts' in value ? (value.provider_counts as unknown) : undefined;
  const rawMissingProviders =
    'missing_providers' in value ? (value.missing_providers as unknown) : undefined;
  const provider_counts: Record<string, number> = {};

  if (rawProviderCounts && !Array.isArray(rawProviderCounts) && typeof rawProviderCounts === 'object') {
    for (const [key, count] of Object.entries(rawProviderCounts)) {
      if (typeof count === 'number' && Number.isFinite(count)) {
        provider_counts[key] = count;
      }
    }
  }

  return {
    provider_counts,
    missing_providers: asStringList(rawMissingProviders),
  };
}

function asSourceType(value: unknown): ResearchSourceType | null {
  return value === 'web' || value === 'paper' ? value : null;
}

function asResearchSourceLedgerEntries(
  artifact: ResearchArtifactRead | undefined,
  contractErrors: string[]
): ResearchSourceLedgerEntry[] {
  const value = artifact?.content_json;
  if (artifact && !Array.isArray(value)) {
    pushContractError(contractErrors, artifact.artifact_key, '数组');
    return [];
  }
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((item) => {
    if (!item || Array.isArray(item) || typeof item !== 'object') {
      return [];
    }
    const entry = item as Record<string, unknown>;
    return [
      {
        provider: typeof entry.provider === 'string' ? entry.provider : null,
        origin_url: typeof entry.origin_url === 'string' ? entry.origin_url : null,
        title: typeof entry.title === 'string' ? entry.title : null,
        source_type: asSourceType(entry.source_type),
      },
    ].filter((candidate) => candidate.provider || candidate.origin_url || candidate.title || candidate.source_type);
  });
}

function asClaimVerdict(value: unknown): ResearchClaimVerdict | null {
  return value === 'supported' || value === 'contested' || value === 'insufficient'
    ? value
    : null;
}

function asResearchClaimMapEntries(
  artifact: ResearchArtifactRead | undefined,
  contractErrors: string[]
): ResearchClaimMapEntry[] {
  const value = artifact?.content_json;
  if (artifact && !Array.isArray(value)) {
    pushContractError(contractErrors, artifact.artifact_key, '数组');
    return [];
  }
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((item) => {
    if (!item || Array.isArray(item) || typeof item !== 'object') {
      return [];
    }
    const entry = item as Record<string, unknown>;
    if (typeof entry.claim !== 'string') {
      return [];
    }

    const verdict = asClaimVerdict(entry.verdict);
    if (!verdict) {
      return [];
    }

    return [
      {
        claim: entry.claim as string,
        verdict,
        citation_indices: asCitationIndices(entry.citation_indices),
      },
    ];
  });
}

function asResearchConflictEntries(
  artifact: ResearchArtifactRead | undefined,
  contractErrors: string[]
): ResearchConflictEntry[] {
  const value = artifact?.content_json;
  if (artifact && !Array.isArray(value)) {
    pushContractError(contractErrors, artifact.artifact_key, '数组');
    return [];
  }
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((item) => {
    if (!item || Array.isArray(item) || typeof item !== 'object') {
      return [];
    }
    const entry = item as Record<string, unknown>;
    if (entry.claim !== null && typeof entry.claim !== 'string' && entry.claim !== undefined) {
      return [];
    }

    const verdict = asClaimVerdict(entry.verdict);
    if (!verdict || typeof entry.reason !== 'string') {
      return [];
    }

    return [
      {
        claim: (entry.claim as string | null | undefined) ?? null,
        verdict,
        reason: entry.reason,
        citation_indices: asCitationIndices(entry.citation_indices),
        coverage_gaps: asStringList(entry.coverage_gaps),
      },
    ];
  });
}

function countPlanSubtasks(planMarkdown: string | null): number {
  if (!planMarkdown) {
    return 0;
  }

  const subtasksSection =
    planMarkdown.match(/##\s+Subtasks\s*\n([\s\S]*?)(?:\n##\s+|\s*$)/i)?.[1] ?? '';
  return subtasksSection
    .split(/\r?\n/)
    .filter((line) => line.trimStart().startsWith('- '))
    .length;
}

function summarizeResearchArtifacts(artifacts: ResearchArtifactRead[]): ResearchArtifactSummary {
  let interimSummary: string | null = null;
  let coverageGap: string | null = null;

  for (const artifact of artifacts) {
    if (artifact.artifact_key === 'interim_summary' && interimSummary === null) {
      interimSummary = readArtifactMarkdown(artifact);
      continue;
    }
    if (artifact.artifact_key === 'coverage_gaps' && coverageGap === null) {
      coverageGap = readCoverageGap(artifact);
    }
  }

  return {
    interimSummary,
    coverageGap,
  };
}

function readEventText(payload: Record<string, unknown>, key: 'summary' | 'finding'): string | null {
  const value = payload[key];
  return typeof value === 'string' && value.trim().length > 0 ? value.trim() : null;
}

function formatSystemEventTitle(event: ResearchEventEnvelope, summary: string | null): string {
  if (summary) {
    return summary;
  }

  switch (event.event_type) {
    case 'research.run.started':
      return '研究已启动';
    case 'research.finalizer.started':
      return '开始生成最终报告';
    case 'research.final.completed':
      return '最终报告已完成';
    case 'research.run.interrupted':
      return '研究已中断';
    case 'research.run.resume_requested':
      return '正在恢复研究';
    case 'research.run.failed':
      return '研究失败';
    case 'research.run.timed_out':
      return '研究已超时';
    default:
      return event.event_type;
  }
}

function buildResearchTimelineItem(event: ResearchEventEnvelope): ResearchTimelineItem {
  const summary = readEventText(event.payload, 'summary');
  const finding = readEventText(event.payload, 'finding');

  if (event.origin_url) {
    return {
      id: event.event_id,
      kind: 'web_visit',
      title: summary ?? `访问 ${event.origin_url}`,
      body: finding,
      phaseLabel: event.phase,
      providerLabel: event.source_provider ?? null,
      url: event.origin_url,
    };
  }

  if (finding) {
    return {
      id: event.event_id,
      kind: 'intermediate_result',
      title: summary ?? '阶段性发现',
      body: finding,
      phaseLabel: event.phase,
      providerLabel: event.source_provider ?? null,
      url: null,
    };
  }

  if (
    event.event_type === 'research.run.started' ||
    event.event_type === 'research.finalizer.started' ||
    event.event_type === 'research.final.completed' ||
    event.event_type === 'research.run.interrupted' ||
    event.event_type === 'research.run.resume_requested' ||
    event.event_type === 'research.run.failed' ||
    event.event_type === 'research.run.timed_out'
  ) {
    return {
      id: event.event_id,
      kind: 'system_status',
      title: formatSystemEventTitle(event, summary),
      body: null,
      phaseLabel: event.phase,
      providerLabel: event.source_provider ?? null,
      url: null,
    };
  }

  return {
    id: event.event_id,
    kind: 'thought_summary',
    title: summary ?? '正在整理研究线索',
    body: null,
    phaseLabel: event.phase,
    providerLabel: event.source_provider ?? null,
    url: null,
  };
}

function buildResearchTimelineItems(events: ResearchEventEnvelope[]): ResearchTimelineItem[] {
  return [...events]
    .sort((left, right) => left.sequence - right.sequence)
    .map(buildResearchTimelineItem);
}

export function buildResearchWorkspaceModel(
  artifacts: ResearchArtifactRead[]
): ResearchWorkspaceModel {
  const artifactByKey = buildResearchArtifactsByKey(artifacts);
  const { reportMd, reportJson } = getResearchReportArtifacts(artifacts);
  const planMarkdown = readArtifactMarkdown(artifactByKey.plan_md);
  const contractErrors: string[] = [];

  return {
    contractErrors,
    mission: {
      markdown: readArtifactMarkdown(artifactByKey.mission_md),
    },
    plan: {
      markdown: planMarkdown,
      subtaskCount: countPlanSubtasks(planMarkdown),
    },
    coverage: {
      markdown: readArtifactMarkdown(artifactByKey.coverage_md),
      matrix: asCoverageMatrix(artifactByKey.coverage_matrix_json, contractErrors),
    },
    evidence: {
      sources: asResearchSourceLedgerEntries(artifactByKey.source_ledger_json, contractErrors),
      conflicts: asResearchConflictEntries(artifactByKey.conflicts_json, contractErrors),
    },
    claims: {
      items: asResearchClaimMapEntries(artifactByKey.claim_map_json, contractErrors),
    },
    report: {
      markdown: reportMd,
      json: reportJson,
    },
  };
}

export function buildResearchPageViewModel(params: {
  status: ResearchSessionStatus;
  events: ResearchEventEnvelope[];
  artifacts: ResearchArtifactRead[];
  reportMd: string | null;
}): ResearchPageViewModel {
  const { interimSummary, coverageGap } = summarizeResearchArtifacts(params.artifacts);
  const workspaceModel = buildResearchWorkspaceModel(params.artifacts);
  const timelineItems = buildResearchTimelineItems(params.events);

  if (interimSummary) {
    timelineItems.push({
      id: 'artifact-interim-summary',
      kind: 'intermediate_result',
      title: '阶段性发现',
      body: interimSummary,
      phaseLabel: params.status,
      providerLabel: null,
      url: null,
    });
  }

  return {
    surface: params.reportMd ? 'final-report' : 'live-research',
    timelineItems: params.reportMd ? [] : timelineItems,
    evidenceDrawer: {
      contractErrors: workspaceModel.contractErrors,
      coverageGap,
      coverageMarkdown: workspaceModel.coverage.markdown,
      coverageMatrix: workspaceModel.coverage.matrix,
      sources: workspaceModel.evidence.sources,
      claims: workspaceModel.claims.items,
      conflicts: workspaceModel.evidence.conflicts,
    },
    report: params.reportMd
      ? {
          markdown: params.reportMd,
        }
      : undefined,
  };
}

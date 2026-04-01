import type {
  ResearchArtifactRead,
  ResearchClaimMapEntry,
  ResearchClaimVerdict,
  ResearchConflictEntry,
  ResearchCoverageMatrix,
  ResearchEventEnvelope,
  ResearchSourceLedgerEntry,
  ResearchSessionStatus,
  ResearchSourceType,
} from '../types/researchEvents';

import {
  buildResearchArtifactsByKey,
  getResearchReportArtifacts,
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
    ].filter(
      (entry) => entry.provider || entry.origin_url || entry.title || entry.source_type
    );
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

import type {
  ResearchArtifactRead,
  ResearchClaimMapEntry,
  ResearchClaimVerdict,
  ResearchClarificationRequest,
  ResearchConflictEntry,
  ResearchCoverageMatrix,
  ResearchEventEnvelope,
  ResearchPlanSnapshot,
  ResearchPresentationSnapshot,
  ResearchSessionStatus,
  ResearchSourceLedgerEntry,
  ResearchSourceTarget,
  ResearchSourceType,
} from '../types/researchEvents';
import { buildResearchArtifactsByKey, getResearchReportArtifacts } from '../types/researchEvents';

const HEADING_REPLACEMENTS: ReadonlyArray<[RegExp, string]> = [
  [/^# Research Report$/gm, '# 研究报告'],
  [/^## Executive Summary$/gm, '## 执行摘要'],
  [/^## Findings$/gm, '## 关键发现'],
  [/^## Coverage Gaps$/gm, '## 覆盖缺口'],
  [/^## References$/gm, '## 参考来源'],
];

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
  coverageGap: string | null;
  coverageMarkdown: string | null;
  coverageMatrix: ResearchCoverageMatrix;
  sources: ResearchSourceLedgerEntry[];
  claims: ResearchClaimMapEntry[];
  conflicts: ResearchConflictEntry[];
}

export interface ResearchHeroModel {
  eyebrow: string;
  title: string;
  subtitle: string;
}

export interface ResearchRailStepModel {
  key: string;
  label: string;
  state: 'pending' | 'current' | 'complete';
}

export interface ResearchClarificationSectionModel {
  summary: string;
  knownContext: string;
  inputPlaceholder: string;
  submitLabel: string;
  questionCards: Array<{ id: string; title: string; description: string }>;
}

export interface ResearchPlanSectionModel {
  researchBrief: string;
  summary: string;
  steps: Array<{ index: number; title: string; description: string; targetSources: string[] }>;
  secondaryActionLabel: string;
  primaryActionLabel: string;
}

export interface ResearchLiveSectionModel {
  progress: {
    label: string;
    percent: number;
    currentStageLabel: string;
  };
  coverageLabel: string;
  activity: Array<{ id: string; eventType: string; title: string; body: string | null; phase: string }>;
  timelineItems: ResearchTimelineItem[];
}

export interface ResearchReportSectionModel {
  markdown: string;
  summary: string;
  outline: Array<{ id: string; title: string; level: number }>;
  metricCards: Array<{ label: string; value: string }>;
}

export interface ResearchPageViewModel {
  surface: 'clarifying' | 'planning' | 'live' | 'final';
  hero: ResearchHeroModel;
  railSteps: ResearchRailStepModel[];
  evidenceDrawer: ResearchEvidenceDrawerModel;
  clarification?: ResearchClarificationSectionModel;
  plan?: ResearchPlanSectionModel;
  live?: ResearchLiveSectionModel;
  report?: ResearchReportSectionModel;
}

const DEFAULT_COVERAGE_MATRIX: ResearchCoverageMatrix = {
  provider_counts: {},
  missing_providers: [],
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && !Array.isArray(value) && typeof value === 'object'
    ? (value as Record<string, unknown>)
    : null;
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    : [];
}

function localizeMarkdown(markdown: string): string {
  return HEADING_REPLACEMENTS.reduce(
    (current, [pattern, replacement]) => current.replace(pattern, replacement),
    markdown
  );
}

function readArtifactText(artifact: ResearchArtifactRead | undefined): string | null {
  return typeof artifact?.content_text === 'string' && artifact.content_text.trim()
    ? localizeMarkdown(artifact.content_text)
    : null;
}

function readReportMarkdown(
  reportMd: string | null,
  reportJson: Record<string, unknown> | null
): string | null {
  if (reportMd && reportMd.trim()) {
    return localizeMarkdown(reportMd);
  }
  if (!reportJson) {
    return null;
  }
  const lines = ['# 研究报告'];
  if (typeof reportJson.summary === 'string' && reportJson.summary.trim()) {
    lines.push(`## 执行摘要\n${reportJson.summary.trim()}`);
  }
  if (Array.isArray(reportJson.findings) && reportJson.findings.length > 0) {
    lines.push(`## 关键发现\n${reportJson.findings.map((item) => `- ${String(item)}`).join('\n')}`);
  }
  return lines.join('\n\n');
}

function toSourceType(value: unknown): ResearchSourceType | null {
  return value === 'web' || value === 'paper' || value === 'kb' ? value : null;
}

function toClaimVerdict(value: unknown): ResearchClaimVerdict | null {
  return value === 'supported' || value === 'contested' || value === 'insufficient' ? value : null;
}

function buildEvidenceDrawer(
  artifactByKey: Record<string, ResearchArtifactRead>
): ResearchEvidenceDrawerModel {
  const coverageArtifact = asRecord(artifactByKey.coverage_matrix_json?.content_json);
  const coverageMatrix: ResearchCoverageMatrix = coverageArtifact
    ? {
        provider_counts:
          asRecord(coverageArtifact.provider_counts)
            ? Object.fromEntries(
                Object.entries(coverageArtifact.provider_counts as Record<string, unknown>).flatMap(
                  ([key, value]) => (typeof value === 'number' ? [[key, value]] : [])
                )
              )
            : {},
        missing_providers: asStringList(coverageArtifact.missing_providers),
      }
    : { ...DEFAULT_COVERAGE_MATRIX };

  const sources = Array.isArray(artifactByKey.source_ledger_json?.content_json)
    ? artifactByKey.source_ledger_json!.content_json.flatMap((item) => {
        const entry = asRecord(item);
        if (!entry) {
          return [];
        }
        return [
          {
            provider: typeof entry.provider === 'string' ? entry.provider : null,
            origin_url: typeof entry.origin_url === 'string' ? entry.origin_url : null,
            title: typeof entry.title === 'string' ? entry.title : null,
            source_type: toSourceType(entry.source_type),
          },
        ];
      })
    : [];

  const claims = Array.isArray(artifactByKey.claim_map_json?.content_json)
    ? artifactByKey.claim_map_json!.content_json.flatMap((item) => {
        const entry = asRecord(item);
        const verdict = entry ? toClaimVerdict(entry.verdict) : null;
        return entry && typeof entry.claim === 'string' && verdict
          ? [
              {
                claim: entry.claim,
                verdict,
                citation_indices: Array.isArray(entry.citation_indices)
                  ? entry.citation_indices.filter((value): value is number => typeof value === 'number')
                  : [],
              },
            ]
          : [];
      })
    : [];

  const conflicts = Array.isArray(artifactByKey.conflicts_json?.content_json)
    ? artifactByKey.conflicts_json!.content_json.flatMap((item) => {
        const entry = asRecord(item);
        const verdict = entry ? toClaimVerdict(entry.verdict) : null;
        return entry && typeof entry.reason === 'string' && verdict
          ? [
              {
                claim: typeof entry.claim === 'string' ? entry.claim : null,
                verdict,
                reason: entry.reason,
                citation_indices: Array.isArray(entry.citation_indices)
                  ? entry.citation_indices.filter((value): value is number => typeof value === 'number')
                  : [],
                coverage_gaps: asStringList(entry.coverage_gaps),
              },
            ]
          : [];
      })
    : [];

  const coverageGap = Array.isArray(artifactByKey.coverage_gaps?.content_json)
    ? (artifactByKey.coverage_gaps!.content_json as unknown[])
        .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
        .join('\n')
    : readArtifactText(artifactByKey.coverage_gaps);

  return {
    coverageGap,
    coverageMarkdown: readArtifactText(artifactByKey.coverage_md),
    coverageMatrix,
    sources,
    claims,
    conflicts,
  };
}

function localizePhase(phase: string): string {
  switch (phase) {
    case 'runtime':
      return '执行阶段';
    case 'finalizer':
      return '收口阶段';
    case 'planner':
      return '规划阶段';
    default:
      return phase;
  }
}

function buildTimelineItem(event: ResearchEventEnvelope): ResearchTimelineItem {
  const summary = typeof event.payload.summary === 'string' ? event.payload.summary.trim() : null;
  const finding = typeof event.payload.finding === 'string' ? event.payload.finding.trim() : null;
  if (event.origin_url) {
    return {
      id: event.event_id,
      kind: 'web_visit',
      title: summary ?? `访问 ${event.origin_url}`,
      body: finding,
      phaseLabel: localizePhase(event.phase),
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
      phaseLabel: localizePhase(event.phase),
      providerLabel: event.source_provider ?? null,
      url: null,
    };
  }
  const title =
    summary ??
    ({
      'research.run.started': '研究已启动',
      'research.finalizer.started': '开始生成最终报告',
      'research.final.completed': '最终报告已完成',
      'research.run.failed': '研究失败',
      'research.run.stopped': '研究已停止',
      'research.run.timed_out': '研究已超时',
    }[event.event_type] ||
      '正在整理研究线索');
  return {
    id: event.event_id,
    kind:
      event.event_type === 'research.run.started' ||
      event.event_type === 'research.finalizer.started' ||
      event.event_type === 'research.final.completed' ||
      event.event_type === 'research.run.failed' ||
      event.event_type === 'research.run.stopped' ||
      event.event_type === 'research.run.timed_out'
        ? 'system_status'
        : 'thought_summary',
    title,
    body: null,
    phaseLabel: localizePhase(event.phase),
    providerLabel: event.source_provider ?? null,
    url: null,
  };
}

function buildTimelineItems(events: ResearchEventEnvelope[], interimSummary: string | null): ResearchTimelineItem[] {
  const items = [...events].sort((a, b) => a.sequence - b.sequence).map(buildTimelineItem);
  if (interimSummary) {
    items.push({
      id: 'artifact-interim-summary',
      kind: 'intermediate_result',
      title: '阶段性发现',
      body: interimSummary,
      phaseLabel: '研究中',
      providerLabel: null,
      url: null,
    });
  }
  return items;
}

function readPresentationSnapshot(
  artifactByKey: Record<string, ResearchArtifactRead>
): ResearchPresentationSnapshot | null {
  const artifact = artifactByKey.presentation_snapshot;
  return artifact?.content_json && !Array.isArray(artifact.content_json)
    ? (artifact.content_json as unknown as ResearchPresentationSnapshot)
    : null;
}

function buildHero(question: string, subtitle: string): ResearchHeroModel {
  return {
    eyebrow: 'Deep Research',
    title: question.trim() || '未命名研究任务',
    subtitle,
  };
}

function buildRailSteps(status: ResearchSessionStatus): ResearchRailStepModel[] {
  if (status === 'clarifying') {
    return [
      { key: 'clarify', label: '澄清问题', state: 'current' },
      { key: 'plan', label: '研究计划', state: 'pending' },
      { key: 'run', label: '执行研究', state: 'pending' },
      { key: 'report', label: '输出报告', state: 'pending' },
    ];
  }
  if (status === 'created' || status === 'planning' || status === 'plan_ready') {
    return [
      { key: 'clarify', label: '澄清问题', state: 'complete' },
      { key: 'plan', label: '研究计划', state: 'current' },
      { key: 'run', label: '执行研究', state: 'pending' },
      { key: 'report', label: '输出报告', state: 'pending' },
    ];
  }
  if (status === 'final') {
    return [
      { key: 'clarify', label: '澄清问题', state: 'complete' },
      { key: 'plan', label: '研究计划', state: 'complete' },
      { key: 'run', label: '执行研究', state: 'complete' },
      { key: 'report', label: '输出报告', state: 'current' },
    ];
  }
  return [
    { key: 'clarify', label: '澄清问题', state: 'complete' },
    { key: 'plan', label: '研究计划', state: 'complete' },
    { key: 'run', label: '执行研究', state: 'current' },
    { key: 'report', label: '输出报告', state: 'pending' },
  ];
}

function formatTargetSource(source: ResearchSourceTarget | string): string {
  switch (source) {
    case 'web':
      return '网页';
    case 'paper':
      return '论文';
    case 'kb':
      return '知识库';
    case 'hybrid':
      return '混合';
    default:
      return String(source);
  }
}

function buildReportOutline(markdown: string): Array<{ id: string; title: string; level: number }> {
  return markdown
    .split(/\r?\n/)
    .filter((line) => line.startsWith('## '))
    .map((line, index) => ({
      id: `section-${index + 1}`,
      title: line.replace(/^##\s+/, '').trim(),
      level: 2,
    }));
}

function buildRecentActivityItems(
  events: ResearchEventEnvelope[]
): Array<{ id: string; eventType: string; title: string; body: string | null; phase: string }> {
  return [...events]
    .sort((a, b) => b.sequence - a.sequence)
    .slice(0, 3)
    .map((event) => {
      const timelineItem = buildTimelineItem(event);
      return {
        id: event.event_id,
        eventType: event.event_type,
        title: timelineItem.title,
        body: timelineItem.body,
        phase: event.phase,
      };
    });
}

function buildCoverageLabel(coverageMatrix: ResearchCoverageMatrix): string {
  const providerCount = Object.keys(coverageMatrix.provider_counts).length;
  const missingCount = coverageMatrix.missing_providers.length;

  if (providerCount > 0 && missingCount > 0) {
    return `已覆盖 ${providerCount} 个来源 / ${missingCount} 个待补缺口`;
  }
  if (providerCount > 0) {
    return `已覆盖 ${providerCount} 个来源`;
  }
  if (missingCount > 0) {
    return `待补 ${missingCount} 个来源缺口`;
  }

  return '覆盖信息生成中';
}

function buildReportMetricCards(evidenceDrawer: ResearchEvidenceDrawerModel): Array<{ label: string; value: string }> {
  const sourceCount = evidenceDrawer.sources.length;
  const claimCount = evidenceDrawer.claims.length;
  const missingCount = evidenceDrawer.coverageMatrix.missing_providers.length;

  return [
    { label: '引用数', value: String(sourceCount) },
    { label: '关键结论', value: String(claimCount) },
    {
      label: '证据状态',
      value: missingCount > 0 ? `待补 ${missingCount} 项` : '覆盖完成',
    },
  ];
}

export function buildResearchPageViewModel(params: {
  question: string;
  status: ResearchSessionStatus;
  events: ResearchEventEnvelope[];
  artifacts: ResearchArtifactRead[];
  reportMd: string | null;
  clarificationRequest?: ResearchClarificationRequest | null;
  planSnapshot?: ResearchPlanSnapshot | null;
}): ResearchPageViewModel {
  const artifactByKey = buildResearchArtifactsByKey(params.artifacts);
  const { reportJson } = getResearchReportArtifacts(params.artifacts);
  const presentation = readPresentationSnapshot(artifactByKey);
  const interimSummary = readArtifactText(artifactByKey.interim_summary);
  const evidenceDrawer = buildEvidenceDrawer(artifactByKey);
  const timelineItems = buildTimelineItems(params.events, interimSummary);
  const reportMarkdown = readReportMarkdown(params.reportMd, reportJson);

  if (presentation) {
    const hero = presentation.hero
      ? { eyebrow: presentation.hero.eyebrow, title: presentation.hero.title, subtitle: presentation.hero.subtitle }
      : buildHero(params.question, '');
    const railSteps = (presentation.rail?.steps ?? []).map((item) => ({ key: item.key, label: item.label, state: item.state }));
    if (presentation.surface === 'clarifying') {
      return {
        surface: 'clarifying',
        hero,
        railSteps,
        evidenceDrawer,
        clarification: presentation.clarification
          ? {
              summary: presentation.clarification.summary,
              knownContext: presentation.clarification.known_context,
              inputPlaceholder: presentation.clarification.input_placeholder,
              submitLabel: presentation.clarification.submit_label,
              questionCards: presentation.clarification.question_cards.map((item) => ({
                id: item.id,
                title: item.title,
                description: item.description,
              })),
            }
          : undefined,
      };
    }
    if (presentation.surface === 'planning') {
      return {
        surface: 'planning',
        hero,
        railSteps,
        evidenceDrawer,
        plan: presentation.plan
          ? {
              researchBrief: presentation.plan.research_brief,
              summary: presentation.plan.summary,
              steps: presentation.plan.steps.map((item) => ({
                index: item.index,
                title: item.title,
                description: item.description,
                targetSources: item.target_sources.map(formatTargetSource),
              })),
              secondaryActionLabel: presentation.plan.secondary_action.label,
              primaryActionLabel: presentation.plan.primary_action.label,
            }
          : undefined,
      };
    }
    if (presentation.surface === 'final') {
      return {
        surface: 'final',
        hero,
        railSteps,
        evidenceDrawer,
        report: {
          markdown: reportMarkdown ?? presentation.report?.markdown ?? '',
          summary: presentation.report?.summary ?? '',
          outline: (presentation.report?.outline ?? []).map((item) => ({ id: item.id, title: item.title, level: item.level })),
          metricCards: (presentation.report?.metric_cards ?? []).map((item) => ({ label: item.label, value: item.value })),
        },
      };
    }
    return {
      surface: 'live',
      hero,
      railSteps,
      evidenceDrawer,
      live: {
        progress: {
          label: presentation.live?.progress.label ?? '研究执行中',
          percent: presentation.live?.progress.percent ?? 64,
          currentStageLabel: presentation.live?.progress.current_stage_label ?? '执行研究',
        },
        coverageLabel: presentation.live?.coverage_label ?? '覆盖信息生成中',
        activity: (presentation.live?.activity ?? []).map((item) => ({
          id: item.id,
          eventType: item.event_type,
          title: item.title,
          body: item.body,
          phase: item.phase,
        })),
        timelineItems,
      },
    };
  }

  if (reportMarkdown) {
    return {
      surface: 'final',
      hero: buildHero(params.question, '研究报告已生成，可直接阅读与导出。'),
      railSteps: buildRailSteps(params.status),
      evidenceDrawer,
      report: {
        markdown: reportMarkdown,
        summary: reportJson && typeof reportJson.summary === 'string' ? reportJson.summary : '研究报告已生成，可直接阅读与导出。',
        outline: buildReportOutline(reportMarkdown),
        metricCards: buildReportMetricCards(evidenceDrawer),
      },
    };
  }

  if (params.status === 'clarifying') {
    return {
      surface: 'clarifying',
      hero: buildHero(params.question, params.clarificationRequest?.summary ?? '请先补齐研究边界。'),
      railSteps: buildRailSteps(params.status),
      evidenceDrawer,
      clarification: {
        summary: params.clarificationRequest?.summary ?? '请先补齐研究边界。',
        knownContext: `当前已收到的研究问题是：${params.question.trim()}`,
        inputPlaceholder: '回复以上问题以优化研究路径…',
        submitLabel: '提交补充信息',
        questionCards: (params.clarificationRequest?.questions ?? []).map((item) => ({
          id: item.id,
          title: item.question,
          description: item.why_it_matters,
        })),
      },
    };
  }

  if (params.status === 'created' || params.status === 'planning' || params.status === 'plan_ready') {
    return {
      surface: 'planning',
      hero: buildHero(params.question, params.planSnapshot?.summary ?? '研究计划已生成，可继续调整后开始执行。'),
      railSteps: buildRailSteps(params.status),
      evidenceDrawer,
      plan: {
        researchBrief: params.planSnapshot?.research_brief ?? '',
        summary: params.planSnapshot?.summary ?? '研究计划已生成，可继续调整后开始执行。',
        steps: (params.planSnapshot?.subtasks ?? []).map((item, index) => ({
          index: index + 1,
          title: item.title,
          description: item.description,
          targetSources: item.target_sources.map(formatTargetSource),
        })),
        secondaryActionLabel: '更新计划',
        primaryActionLabel: '开始研究',
      },
    };
  }

  return {
    surface: 'live',
    hero: buildHero(params.question, '正在整合研究线索、证据与中间发现。'),
    railSteps: buildRailSteps(params.status),
    evidenceDrawer,
    live: {
      progress:
        params.status === 'queued'
          ? { label: '研究准备中', percent: 28, currentStageLabel: '进入执行队列' }
          : params.status === 'finalizing'
            ? { label: '报告生成中', percent: 88, currentStageLabel: '生成报告' }
            : { label: '研究执行中', percent: 64, currentStageLabel: '执行研究' },
      coverageLabel: buildCoverageLabel(evidenceDrawer.coverageMatrix),
      activity: buildRecentActivityItems(params.events),
      timelineItems,
    },
  };
}

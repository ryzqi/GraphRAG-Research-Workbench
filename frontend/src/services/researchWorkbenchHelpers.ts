import type {
  ResearchArtifactRead,
  ResearchClaimVerdict,
  ResearchCoverageMatrix,
  ResearchEventEnvelope,
  ResearchPlanSnapshot,
  ResearchPresentationSnapshot,
  ResearchSessionStatus,
  ResearchSourceTarget,
  ResearchSourceType,
} from '../types/researchEvents';
import type {
  ResearchEvidenceDrawerModel,
  ResearchHeroModel,
  ResearchLiveSectionModel,
  ResearchLiveStepState,
  ResearchRailStepModel,
  ResearchTimelineItem,
} from './researchWorkbenchModels';

const HEADING_REPLACEMENTS: ReadonlyArray<[RegExp, string]> = [
  [/^# Research Report$/gm, '# 研究报告'],
  [/^## Executive Summary$/gm, '## 执行摘要'],
  [/^## Findings$/gm, '## 关键发现'],
  [/^## Coverage Gaps$/gm, '## 覆盖缺口'],
  [/^## References$/gm, '## 参考来源'],
];

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

export function localizeMarkdown(markdown: string): string {
  return HEADING_REPLACEMENTS.reduce(
    (current, [pattern, replacement]) => current.replace(pattern, replacement),
    markdown
  );
}

export function readArtifactText(artifact: ResearchArtifactRead | undefined): string | null {
  return typeof artifact?.content_text === 'string' && artifact.content_text.trim()
    ? localizeMarkdown(artifact.content_text)
    : null;
}

function toSourceType(value: unknown): ResearchSourceType | null {
  return value === 'web' || value === 'paper' || value === 'kb' ? value : null;
}

function toClaimVerdict(value: unknown): ResearchClaimVerdict | null {
  return value === 'supported' || value === 'contested' || value === 'insufficient' ? value : null;
}

export function buildEvidenceDrawer(
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

export function buildTimelineItems(
  events: ResearchEventEnvelope[],
  interimSummary: string | null
): ResearchTimelineItem[] {
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

export function readPresentationSnapshot(
  artifactByKey: Record<string, ResearchArtifactRead>
): ResearchPresentationSnapshot | null {
  const artifact = artifactByKey.presentation_snapshot;
  return artifact?.content_json && !Array.isArray(artifact.content_json)
    ? (artifact.content_json as unknown as ResearchPresentationSnapshot)
    : null;
}

export function buildHero(question: string, subtitle: string): ResearchHeroModel {
  return {
    eyebrow: 'Deep Research',
    title: question.trim() || '未命名研究任务',
    subtitle,
  };
}

export function buildRailSteps(status: ResearchSessionStatus): ResearchRailStepModel[] {
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

export function formatTargetSource(source: ResearchSourceTarget | string): string {
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

export function buildLiveActivityCards(params: {
  events: ResearchEventEnvelope[];
  fallbackActivity?: Array<{ id: string; event_type: string; title: string; body: string | null; phase: string }>;
}): Array<{
  id: string;
  eventType: string;
  title: string;
  body: string | null;
  phase: string;
  tone?: 'default' | 'live' | 'success' | 'warning';
}> {
  const recentEvents = [...params.events].sort((a, b) => b.sequence - a.sequence).slice(0, 3);
  if (recentEvents.length > 0) {
    return recentEvents.map((event) => {
      const timelineItem = buildTimelineItem(event);
      const tone =
        event.event_type === 'research.run.started' || event.event_type === 'research.final.completed'
          ? 'success'
          : event.event_type === 'research.run.failed' ||
              event.event_type === 'research.run.timed_out' ||
              event.event_type === 'research.run.stopped'
            ? 'warning'
            : event.event_type === 'research.trace.recorded'
              ? 'live'
              : 'default';
      return {
        id: event.event_id,
        eventType: event.event_type,
        title: timelineItem.title,
        body: timelineItem.body,
        phase: event.phase,
        tone,
      };
    });
  }

  return (params.fallbackActivity ?? []).slice(0, 3).map((item) => ({
    id: item.id,
    eventType: item.event_type,
    title: item.title,
    body: item.body,
    phase: item.phase,
    tone: item.event_type === 'research.trace.recorded' ? 'live' : 'default',
  }));
}

export function normalizeParallelTasks(
  value: ResearchPresentationSnapshot['live'] | null | undefined
): ResearchLiveSectionModel['parallelTasks'] {
  return (value?.parallel_tasks ?? []).map((item) => ({
    id: item.task_id,
    label: item.title,
    taskKind: item.task_kind ?? null,
    status: item.status ?? null,
    agentLabel: item.agent_label ?? null,
    parallelGroup: item.parallel_group ?? null,
  }));
}

export function buildLivePlanSteps(params: {
  status: ResearchSessionStatus;
  planSnapshot?: ResearchPlanSnapshot | null;
}): Array<{
  key: string;
  label: string;
  state: ResearchLiveStepState;
}> {
  const { status, planSnapshot } = params;
  const planSteps: Array<{ key: string; label: string; state: ResearchLiveStepState }> = (
    planSnapshot?.subtasks ?? []
  ).map((item, index) => ({
    key: `plan-step-${index + 1}`,
    label: item.title,
    state:
      status === 'finalizing' || status === 'final'
        ? 'complete'
        : status === 'canceled'
          ? index === 0
            ? 'canceled'
            : 'pending'
          : status === 'failed' || status === 'timed_out'
            ? index === 0
              ? 'failed'
              : 'pending'
            : index === 0
              ? 'current'
              : 'pending',
  }));
  if (planSteps.length > 0) {
    return planSteps;
  }

  if (status === 'queued') {
    return [
      { key: 'plan-step-1', label: '进入执行队列', state: 'current' },
      { key: 'plan-step-2', label: '执行研究', state: 'pending' },
      { key: 'plan-step-3', label: '生成报告', state: 'pending' },
    ];
  }

  if (status === 'finalizing' || status === 'final') {
    return [
      { key: 'plan-step-1', label: '进入执行队列', state: 'complete' },
      { key: 'plan-step-2', label: '执行研究', state: 'complete' },
      { key: 'plan-step-3', label: '生成报告', state: 'current' },
    ];
  }

  return [
    { key: 'plan-step-1', label: '进入执行队列', state: 'complete' },
    { key: 'plan-step-2', label: '执行研究', state: 'current' },
    { key: 'plan-step-3', label: '生成报告', state: 'pending' },
  ];
}

function resolveCurrentPlanStepLabel(
  planSteps: Array<{
    key: string;
    label: string;
    state: ResearchLiveStepState;
  }>
): string | null {
  const currentStep = planSteps.find((item) =>
    item.state === 'current' || item.state === 'failed' || item.state === 'canceled'
  );
  return currentStep?.label ?? null;
}

export function buildLiveProgress(params: {
  status: ResearchSessionStatus;
  planSteps: Array<{
    key: string;
    label: string;
    state: ResearchLiveStepState;
  }>;
}): ResearchLiveSectionModel['progress'] {
  const { status, planSteps } = params;
  const totalSteps = planSteps.length;
  const completedStepCount = planSteps.filter((item) => item.state === 'complete').length;
  const currentStageLabel = resolveCurrentPlanStepLabel(planSteps);
  const planPercent = totalSteps > 0 ? Math.round((completedStepCount / totalSteps) * 100) : 0;

  if (status === 'queued') {
    return { label: '研究准备中', percent: planPercent, currentStageLabel: currentStageLabel ?? '进入执行队列' };
  }
  if (status === 'finalizing') {
    return { label: '报告生成中', percent: 88, currentStageLabel: '生成报告' };
  }
  if (status === 'failed') {
    return { label: '研究失败', percent: planPercent, currentStageLabel: currentStageLabel ?? '研究失败' };
  }
  if (status === 'canceled') {
    return { label: '研究已停止', percent: planPercent, currentStageLabel: currentStageLabel ?? '研究已停止' };
  }
  if (status === 'timed_out') {
    return { label: '研究超时', percent: planPercent, currentStageLabel: currentStageLabel ?? '研究超时' };
  }
  return { label: '研究执行中', percent: planPercent, currentStageLabel: currentStageLabel ?? '执行研究' };
}

export function buildPendingLiveSection(params: {
  status: ResearchSessionStatus;
  planSnapshot?: ResearchPlanSnapshot | null;
}): ResearchLiveSectionModel {
  const planSteps = buildLivePlanSteps({
    status: params.status,
    planSnapshot: params.planSnapshot,
  });
  return {
    progress: buildLiveProgress({
      status: params.status,
      planSteps,
    }),
    parallelTasks: [],
    planSteps,
    coverageLabel: '研究工件同步中',
    footerStatus: '系统正在同步最新研究工件',
    activity: [],
    timelineItems: [],
  };
}

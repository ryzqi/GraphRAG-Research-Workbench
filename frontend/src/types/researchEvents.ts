export type ResearchSessionStatus =
  | 'created'
  | 'planning'
  | 'clarifying'
  | 'plan_ready'
  | 'queued'
  | 'running'
  | 'finalizing'
  | 'final'
  | 'failed'
  | 'canceled'
  | 'timed_out';

export type ResearchSourceTarget = 'kb' | 'web' | 'paper' | 'hybrid';
export type ResearchSourceType = 'kb' | 'web' | 'paper';

export interface ResearchSessionCreateRequest {
  question: string;
  plan_first?: boolean;
}

export interface ResearchPlanSubtask {
  title: string;
  description: string;
  target_sources: ResearchSourceTarget[];
}

export interface ResearchPlanSnapshot {
  research_brief: string;
  complexity: 'simple' | 'comparative' | 'complex';
  summary: string;
  subtasks: ResearchPlanSubtask[];
  target_sources: ResearchSourceTarget[];
  budget_guidance?: string | null;
}

export interface ResearchClarificationQuestion {
  id: string;
  question: string;
  why_it_matters: string;
}

export interface ResearchClarificationRequest {
  summary: string;
  questions: ResearchClarificationQuestion[];
}

export interface ResearchSessionAccepted {
  session_id: string;
  question: string;
  status: ResearchSessionStatus;
  plan_snapshot: ResearchPlanSnapshot | null;
  clarification_request: ResearchClarificationRequest | null;
}

export interface ResearchClarificationSubmitRequest {
  answer: string;
}

export interface ResearchPlanUpdateRequest {
  feedback: string;
}

export interface ResearchStopRequest {
  reason?: string | null;
}

export interface ResearchCanonicalCitation {
  source_type: ResearchSourceType;
  source_provider: string;
  retrieval_method: string;
  source_id: string;
  title?: string | null;
  url?: string | null;
  origin_url?: string | null;
  arxiv_id?: string | null;
  authors: string[];
  published_at?: string | null;
  pdf_url?: string | null;
  accessed_at?: string | null;
}

export interface ResearchSourceLedgerEntry {
  provider: string | null;
  origin_url: string | null;
  title: string | null;
  source_type: ResearchSourceType | null;
}

export type ResearchClaimVerdict = 'supported' | 'contested' | 'insufficient';

export interface ResearchClaimMapEntry {
  claim: string;
  verdict: ResearchClaimVerdict;
  citation_indices: number[];
}

export interface ResearchConflictEntry {
  claim: string | null;
  verdict: ResearchClaimVerdict;
  reason: string;
  citation_indices: number[];
  coverage_gaps: string[];
}

export interface ResearchCoverageMatrix {
  provider_counts: Record<string, number>;
  missing_providers: string[];
}

export interface ResearchArtifactRead {
  artifact_key: string;
  content_text?: string | null;
  content_json?: Record<string, unknown> | unknown[] | null;
  citations: ResearchCanonicalCitation[];
  source_provider?: string | null;
  retrieval_method?: string | null;
  origin_url?: string | null;
}

export interface ResearchArtifactsResponse {
  session_id: string;
  items: ResearchArtifactRead[];
}

export interface ResearchPresentationHero {
  eyebrow: string;
  title: string;
  subtitle: string;
}

export interface ResearchPresentationRailStep {
  key: string;
  label: string;
  state: 'pending' | 'current' | 'complete';
}

export interface ResearchPresentationClarificationCard {
  id: string;
  title: string;
  description: string;
}

export interface ResearchPresentationClarificationSection {
  summary: string;
  known_context: string;
  input_placeholder: string;
  submit_label: string;
  question_cards: ResearchPresentationClarificationCard[];
}

export interface ResearchPresentationPlanStep {
  index: number;
  title: string;
  description: string;
  target_sources: string[];
}

export interface ResearchPresentationPlanSection {
  research_brief: string;
  summary: string;
  steps: ResearchPresentationPlanStep[];
  secondary_action: {
    label: string;
  };
  primary_action: {
    label: string;
  };
}

export interface ResearchPresentationLiveActivity {
  id: string;
  event_type: string;
  title: string;
  body: string | null;
  phase: string;
}

export interface ResearchPresentationPipelineStep {
  key: string;
  label: string;
  state: 'pending' | 'current' | 'complete' | 'failed' | 'canceled';
}

export interface ResearchPresentationLiveSection {
  progress: {
    label: string;
    percent: number;
    current_stage_label: string;
  };
  coverage_label: string;
  plan_steps?: ResearchPresentationPipelineStep[];
  activity: ResearchPresentationLiveActivity[];
}

export interface ResearchPresentationReportOutlineItem {
  id: string;
  title: string;
  level: number;
}

export interface ResearchPresentationReportMetricCard {
  label: string;
  value: string;
}

export interface ResearchPresentationReportSection {
  badge_label?: string;
  markdown: string;
  summary: string;
  outline: ResearchPresentationReportOutlineItem[];
  metric_cards: ResearchPresentationReportMetricCard[];
}

export interface ResearchPresentationSnapshot {
  surface: 'clarifying' | 'planning' | 'live' | 'final';
  hero?: ResearchPresentationHero;
  rail?: {
    steps: ResearchPresentationRailStep[];
  };
  clarification?: ResearchPresentationClarificationSection | null;
  plan?: ResearchPresentationPlanSection | null;
  live?: ResearchPresentationLiveSection | null;
  report?: ResearchPresentationReportSection | null;
}

export interface ResearchEventEnvelope {
  event_id: string;
  sequence: number;
  timestamp: string;
  event_type: string;
  session_id: string;
  phase: string;
  namespace: string;
  payload: Record<string, unknown>;
  trace_id?: string | null;
  source_provider?: string | null;
  retrieval_method?: string | null;
  origin_url?: string | null;
  lc_agent_name?: string | null;
  subagent_name?: string | null;
}

export interface ResearchStreamCursor {
  lastEventId: string | null;
  lastSequence: number;
}

export interface ResearchSessionView {
  session_id: string;
  question: string;
  status: ResearchSessionStatus;
  plan_snapshot: ResearchPlanSnapshot | null;
  clarification_request: ResearchClarificationRequest | null;
  events: ResearchEventEnvelope[];
  artifacts: ResearchArtifactRead[];
  last_event_id: string | null;
  last_sequence: number;
  report_md: string | null;
  report_json: Record<string, unknown> | null;
}

const TERMINAL_RESEARCH_SESSION_STATUSES: ReadonlySet<ResearchSessionStatus> = new Set([
  'final',
  'failed',
  'canceled',
  'timed_out',
]);

function compareResearchEvents(
  left: ResearchEventEnvelope,
  right: ResearchEventEnvelope
): number {
  if (left.sequence !== right.sequence) {
    return left.sequence - right.sequence;
  }
  return left.event_id.localeCompare(right.event_id);
}

export function mergeResearchEventEnvelopes(
  existing: readonly ResearchEventEnvelope[],
  incoming: readonly ResearchEventEnvelope[]
): ResearchEventEnvelope[] {
  const mergedById = new Map<string, ResearchEventEnvelope>();

  for (const item of [...existing, ...incoming].sort(compareResearchEvents)) {
    if (!mergedById.has(item.event_id)) {
      mergedById.set(item.event_id, item);
    }
  }

  return [...mergedById.values()].sort(compareResearchEvents);
}

export function buildResearchArtifactsByKey(
  items: readonly ResearchArtifactRead[]
): Record<string, ResearchArtifactRead> {
  return Object.fromEntries(items.map((item) => [item.artifact_key, item]));
}

export function getResearchReportArtifacts(
  items: readonly ResearchArtifactRead[]
): {
  reportMd: string | null;
  reportJson: Record<string, unknown> | null;
} {
  const artifactByKey = buildResearchArtifactsByKey(items);
  const reportMdArtifact = artifactByKey.report_md;
  const reportJsonArtifact = artifactByKey.report_json;

  return {
    reportMd:
      typeof reportMdArtifact?.content_text === 'string' &&
      reportMdArtifact.content_text.trim()
        ? reportMdArtifact.content_text
        : null,
    reportJson:
      reportJsonArtifact &&
      reportJsonArtifact.content_json &&
      !Array.isArray(reportJsonArtifact.content_json) &&
      typeof reportJsonArtifact.content_json === 'object'
        ? (reportJsonArtifact.content_json as Record<string, unknown>)
        : null,
  };
}

export function getLatestResearchStreamCursor(
  items: readonly ResearchEventEnvelope[]
): ResearchStreamCursor {
  if (items.length === 0) {
    return {
      lastEventId: null,
      lastSequence: 0,
    };
  }

  const lastItem = [...items].sort(compareResearchEvents).at(-1);
  return {
    lastEventId: lastItem?.event_id ?? null,
    lastSequence: lastItem?.sequence ?? 0,
  };
}

export function isTerminalResearchStatus(status: ResearchSessionStatus): boolean {
  return TERMINAL_RESEARCH_SESSION_STATUSES.has(status);
}

export function deriveResearchStatus(params: {
  acceptedStatus: ResearchSessionStatus;
  events: readonly ResearchEventEnvelope[];
  artifacts?: readonly ResearchArtifactRead[];
}): ResearchSessionStatus {
  const { acceptedStatus, events, artifacts = [] } = params;
  const ordered = [...events].sort(compareResearchEvents);

  for (let index = ordered.length - 1; index >= 0; index -= 1) {
    const eventType = ordered[index]?.event_type;
    switch (eventType) {
      case 'research.final.completed':
        return 'final';
      case 'research.finalizer.started':
        return 'finalizing';
      case 'research.run.stopped':
        return 'canceled';
      case 'research.run.timed_out':
        return 'timed_out';
      case 'research.run.failed':
        return 'failed';
      case 'research.run.started':
        return 'running';
      default:
        break;
    }
  }

  const { reportMd, reportJson } = getResearchReportArtifacts(artifacts);
  if (reportMd && reportJson) {
    return 'final';
  }

  return acceptedStatus;
}

export function buildResearchSessionView(params: {
  accepted: ResearchSessionAccepted;
  events: readonly ResearchEventEnvelope[];
  artifacts: readonly ResearchArtifactRead[];
}): ResearchSessionView {
  const orderedEvents = mergeResearchEventEnvelopes([], params.events);
  const cursor = getLatestResearchStreamCursor(orderedEvents);
  const { reportMd, reportJson } = getResearchReportArtifacts(params.artifacts);

  return {
    session_id: params.accepted.session_id,
    question: params.accepted.question,
    status: deriveResearchStatus({
      acceptedStatus: params.accepted.status,
      events: orderedEvents,
      artifacts: params.artifacts,
    }),
    plan_snapshot: params.accepted.plan_snapshot,
    clarification_request: params.accepted.clarification_request,
    events: orderedEvents,
    artifacts: [...params.artifacts],
    last_event_id: cursor.lastEventId,
    last_sequence: cursor.lastSequence,
    report_md: reportMd,
    report_json: reportJson,
  };
}

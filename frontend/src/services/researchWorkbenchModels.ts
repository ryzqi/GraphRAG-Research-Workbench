import type {
  ResearchClaimMapEntry,
  ResearchConflictEntry,
  ResearchCoverageMatrix,
  ResearchSourceLedgerEntry,
} from '../types/researchEvents';

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

export type ResearchLiveStepState = 'pending' | 'current' | 'complete' | 'failed' | 'canceled';

export interface ResearchLiveSectionModel {
  progress: {
    label: string;
    percent: number;
    currentStageLabel: string;
  };
  currentAgentLabel?: string;
  currentTaskLabel?: string;
  currentTaskKind?: string;
  parallelTasks: Array<{
    id: string;
    label: string;
    taskKind: string | null;
    status: string | null;
    agentLabel: string | null;
    parallelGroup: string | null;
  }>;
  planSteps: Array<{
    key: string;
    label: string;
    state: ResearchLiveStepState;
  }>;
  coverageLabel: string;
  footerStatus?: string;
  activity: Array<{
    id: string;
    eventType: string;
    title: string;
    body: string | null;
    phase: string;
    tone?: 'default' | 'live' | 'success' | 'warning';
  }>;
  timelineItems: ResearchTimelineItem[];
}

export interface ResearchReportSectionModel {
  markdown: string;
  summary: string;
  badgeLabel?: string;
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

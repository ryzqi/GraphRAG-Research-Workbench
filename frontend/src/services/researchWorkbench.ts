import type {
  ResearchArtifactRead,
  ResearchClarificationRequest,
  ResearchEventEnvelope,
  ResearchPlanSnapshot,
  ResearchSessionStatus,
} from '../types/researchEvents';
import { buildResearchArtifactsByKey } from '../types/researchEvents';
import {
  buildEvidenceDrawer,
  buildHero,
  buildLiveActivityCards,
  buildLivePlanSteps,
  buildLiveProgress,
  buildPendingLiveSection,
  buildRailSteps,
  buildTimelineItems,
  formatTargetSource,
  localizeMarkdown,
  normalizeParallelTasks,
  readArtifactText,
  readPresentationSnapshot,
} from './researchWorkbenchHelpers';
import type { ResearchPageViewModel } from './researchWorkbenchModels';

export type {
  ResearchClarificationSectionModel,
  ResearchEvidenceDrawerModel,
  ResearchHeroModel,
  ResearchLiveSectionModel,
  ResearchLiveStepState,
  ResearchPageViewModel,
  ResearchPlanSectionModel,
  ResearchRailStepModel,
  ResearchReportSectionModel,
  ResearchTimelineItem,
} from './researchWorkbenchModels';

export function buildResearchPageViewModel(params: {
  question: string;
  status: ResearchSessionStatus;
  events: ResearchEventEnvelope[];
  artifacts: ResearchArtifactRead[];
  clarificationRequest?: ResearchClarificationRequest | null;
  planSnapshot?: ResearchPlanSnapshot | null;
}): ResearchPageViewModel {
  const artifactByKey = buildResearchArtifactsByKey(params.artifacts);
  const presentation = readPresentationSnapshot(artifactByKey);
  const interimSummary = readArtifactText(artifactByKey.interim_summary);
  const evidenceDrawer = buildEvidenceDrawer(artifactByKey);
  const timelineItems = buildTimelineItems(params.events, interimSummary);

  if (presentation) {
    const hero = presentation.hero
      ? {
          eyebrow: presentation.hero.eyebrow,
          title: presentation.hero.title,
          subtitle: presentation.hero.subtitle,
        }
      : buildHero(params.question, '');
    const railSteps = (presentation.rail?.steps ?? []).map((item) => ({
      key: item.key,
      label: item.label,
      state: item.state,
    }));

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
          markdown: localizeMarkdown(presentation.report?.markdown ?? ''),
          summary: presentation.report?.summary ?? '',
          badgeLabel: presentation.report?.badge_label ?? '已生成研究报告',
          outline: (presentation.report?.outline ?? []).map((item) => ({
            id: item.id,
            title: item.title,
            level: item.level,
          })),
          metricCards: (presentation.report?.metric_cards ?? []).map((item) => ({
            label: item.label,
            value: item.value,
          })),
        },
      };
    }

    return {
      surface: 'live',
      hero,
      railSteps,
      evidenceDrawer,
      live: (() => {
        const planSteps =
          presentation.live?.plan_steps?.map((item) => ({
            key: item.key,
            label: item.label,
            state: item.state,
          })) ?? buildLivePlanSteps({ status: params.status, planSnapshot: params.planSnapshot });
        const fallbackProgress = buildLiveProgress({
          status: params.status,
          planSteps,
        });
        return {
          progress: {
            label: presentation.live?.progress.label ?? fallbackProgress.label,
            percent: presentation.live?.progress.percent ?? fallbackProgress.percent,
            currentStageLabel:
              presentation.live?.progress.current_stage_label ?? fallbackProgress.currentStageLabel,
          },
          currentAgentLabel: presentation.live?.current_agent_label ?? undefined,
          currentTaskLabel: presentation.live?.current_task_label ?? undefined,
          currentTaskKind: presentation.live?.current_task_kind ?? undefined,
          parallelTasks: normalizeParallelTasks(presentation.live),
          planSteps,
          coverageLabel: presentation.live?.coverage_label ?? '覆盖信息生成中',
          footerStatus: `系统运行正常，${presentation.live?.coverage_label ?? '正在收集研究证据'}`,
          activity: buildLiveActivityCards({
            events: params.events,
            fallbackActivity: presentation.live?.activity ?? [],
          }),
          timelineItems,
        };
      })(),
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
      hero: buildHero(
        params.question,
        params.planSnapshot?.summary ?? '研究计划已生成，可继续调整后开始执行。'
      ),
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
    hero: buildHero(
      params.question,
      params.status === 'final' || params.status === 'finalizing'
        ? '正在同步最终报告工件。'
        : '正在同步研究工件。'
    ),
    railSteps: buildRailSteps(params.status),
    evidenceDrawer,
    live: buildPendingLiveSection({
      status: params.status,
      planSnapshot: params.planSnapshot,
    }),
  };
}

'use client';

/**
 * 深度研究页面
 */
import { useCallback, useMemo, useState } from 'react';
import { Container, Stack } from '@mui/material';
import DownloadIcon from '@mui/icons-material/Download';
import RefreshIcon from '@mui/icons-material/Refresh';
import { ArtifactPanel } from '../components/research/ArtifactPanel';
import { InterruptDecisionPanel } from '../components/research/InterruptDecisionPanel';
import { PlanPreviewPanel } from '../components/research/PlanPreviewPanel';
import { ResearchAdvancedEventsPanel } from '../components/research/ResearchAdvancedEventsPanel';
import { ResearchCanvas } from '../components/research/ResearchCanvas';
import { ResearchComposer } from '../components/research/ResearchComposer';
import { ResearchSessionRail } from '../components/research/ResearchSessionRail';
import { ResearchWorkspaceShell } from '../components/research/ResearchWorkspaceShell';
import { Button } from '../components/ui/Button';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { PageHeader } from '../components/ui/PageHeader';
import { createExport, pollExportUntilDone } from '../services/exports';
import {
  buildResearchCanvasModel,
  buildResearchProgressFeed,
  buildResearchSourceSummary,
} from '../services/researchWorkbench';
import {
  useConfirmResearchPlan,
  useCreateResearchSession,
  useInterruptResearchSession,
  useResearchSession,
  useResumeResearchSession,
} from '../hooks/queries/useResearch';
import { getErrorMessage } from '../lib/errorHandler';
import type { ResearchSessionAccepted, ResearchSessionStatus } from '../types/researchEvents';
import { safeOpenDownloadUrl } from '../utils/urlValidation';
import {
  buildResearchStartRequest,
  validateResearchStartDraft,
} from './researchPageState';

export function ResearchPage() {
  const createSessionMutation = useCreateResearchSession();
  const confirmPlanMutation = useConfirmResearchPlan();
  const interruptSessionMutation = useInterruptResearchSession();
  const resumeSessionMutation = useResumeResearchSession();

  const [question, setQuestion] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [acceptedSession, setAcceptedSession] = useState<ResearchSessionAccepted | null>(null);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resumeIdempotencyKey, setResumeIdempotencyKey] = useState('resume-1');
  const [decisionDraft, setDecisionDraft] = useState('[{"action":"approve"}]');

  const sessionQuery = useResearchSession(sessionId ?? undefined, acceptedSession);
  const session = sessionQuery.data;

  const loading = createSessionMutation.isPending;

  const mergedError =
    error ??
    (createSessionMutation.error ? getErrorMessage(createSessionMutation.error) : null) ??
    (confirmPlanMutation.error ? getErrorMessage(confirmPlanMutation.error) : null) ??
    (interruptSessionMutation.error ? getErrorMessage(interruptSessionMutation.error) : null) ??
    (resumeSessionMutation.error ? getErrorMessage(resumeSessionMutation.error) : null) ??
    (sessionQuery.error ? getErrorMessage(sessionQuery.error) : null);

  const handleCloseError = () => {
    if (error) {
      setError(null);
      return;
    }
    if (createSessionMutation.error) {
      createSessionMutation.reset();
      return;
    }
    if (confirmPlanMutation.error) {
      confirmPlanMutation.reset();
      return;
    }
    if (interruptSessionMutation.error) {
      interruptSessionMutation.reset();
      return;
    }
    if (resumeSessionMutation.error) {
      resumeSessionMutation.reset();
      return;
    }
    if (sessionQuery.error) {
      void sessionQuery.refetch();
    }
  };

  const startResearch = useCallback(async () => {
    const validationError = validateResearchStartDraft({
      question,
    });
    if (validationError) {
      setError(validationError);
      return;
    }

    setError(null);
    setSessionId(null);
    setAcceptedSession(null);

    try {
      const newSession = await createSessionMutation.mutateAsync(
        buildResearchStartRequest({
          question,
        })
      );

      setAcceptedSession(newSession);
      setSessionId(newSession.session_id);
      setResumeIdempotencyKey(`resume-${Date.now()}`);
    } catch (e) {
      setError(getErrorMessage(e));
    }
  }, [createSessionMutation, question]);

  const handleConfirmPlan = useCallback(async () => {
    if (!sessionId) {
      return;
    }

    setError(null);
    try {
      const nextAccepted = await confirmPlanMutation.mutateAsync({
        sessionId,
        body: {
          approved: true,
          note: '继续执行',
        },
      });
      setAcceptedSession(nextAccepted);
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
    }
  }, [confirmPlanMutation, sessionId]);

  const handleInterrupt = useCallback(async () => {
    if (!sessionId) {
      return;
    }

    setError(null);
    try {
      const nextAccepted = await interruptSessionMutation.mutateAsync({
        sessionId,
        reason: '前端请求中断，等待人工决策',
      });
      setAcceptedSession(nextAccepted);
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
    }
  }, [interruptSessionMutation, sessionId]);

  const handleResume = useCallback(async () => {
    if (!sessionId) {
      return;
    }

    setError(null);
    try {
      const decisions = JSON.parse(decisionDraft) as Array<Record<string, unknown>>;
      await resumeSessionMutation.mutateAsync({
        sessionId,
        body: {
          idempotency_key: resumeIdempotencyKey.trim() || `resume-${Date.now()}`,
          resume_from_event_id: session?.last_event_id ?? undefined,
          decisions,
        },
      });
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
    }
  }, [decisionDraft, resumeIdempotencyKey, resumeSessionMutation, session?.last_event_id, sessionId]);

  const handleExport = useCallback(async () => {
    if (!session) return;

    setExporting(true);
    setError(null);

    try {
      const job = await createExport({ type: 'research', session_id: session.session_id });
      const completed = await pollExportUntilDone(job.id);

      if (completed.status === 'succeeded' && completed.download_url) {
        if (!safeOpenDownloadUrl(completed.download_url)) {
          setError('下载链接来自不受信任的域名');
        }
      } else {
        setError(completed.error_message || '导出失败');
      }
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setExporting(false);
    }
  }, [session]);

  const reset = useCallback(() => {
    setSessionId(null);
    setAcceptedSession(null);
    setQuestion('');
    setError(null);
    setDecisionDraft('[{"action":"approve"}]');
    setResumeIdempotencyKey('resume-1');
  }, []);

  const getStatusPresentation = (status: ResearchSessionStatus) => {
    switch (status) {
      case 'created':
      case 'planning':
      case 'awaiting_confirmation':
        return { badge: 'pending' as const, label: '等待计划' };
      case 'queued':
        return { badge: 'queued' as const, label: '排队中...' };
      case 'running':
        return { badge: 'running' as const, label: '研究中...' };
      case 'interrupted':
        return { badge: 'pending' as const, label: '已中断' };
      case 'resuming':
        return { badge: 'running' as const, label: '恢复中...' };
      case 'finalizing':
        return { badge: 'running' as const, label: '收口中...' };
      case 'final':
        return { badge: 'succeeded' as const, label: '已完成' };
      case 'canceled':
        return { badge: 'canceled' as const, label: '已取消' };
      case 'timed_out':
      case 'failed':
      default:
        return { badge: 'failed' as const, label: '失败' };
    }
  };

  const statusPresentation = session ? getStatusPresentation(session.status) : null;
  const progressItems = useMemo(
    () => buildResearchProgressFeed(session?.events ?? []),
    [session?.events]
  );
  const sourceSummary = useMemo(() => buildResearchSourceSummary(), []);
  const canvasModel = useMemo(
    () =>
      buildResearchCanvasModel({
        status: session?.status ?? 'created',
        events: session?.events ?? [],
        artifacts: session?.artifacts ?? [],
        reportMd: session?.report_md ?? null,
      }),
    [session]
  );

  return (
    <Container maxWidth="xl" sx={{ py: { xs: 2, md: 3 } }}>
      <PageHeader title="深度研究" />

      {!sessionId ? (
        <ResearchComposer
          question={question}
          loading={loading}
          validationError={validateResearchStartDraft({
            question,
          })}
          onQuestionChange={setQuestion}
          onStart={startResearch}
        />
      ) : !session ? (
        <LoadingSpinner text="加载研究任务..." />
      ) : (
        <ResearchWorkspaceShell
          rail={
            <ResearchSessionRail
              question={question.trim()}
              statusLabel={statusPresentation?.label ?? '等待中'}
              statusTone={statusPresentation?.badge ?? 'pending'}
              progressItems={progressItems}
              sourceSummary={sourceSummary}
              planPanel={
                <PlanPreviewPanel
                  planSnapshot={session.plan_snapshot}
                  status={session.status}
                  onConfirm={handleConfirmPlan}
                  confirmPending={confirmPlanMutation.isPending}
                />
              }
              interruptPanel={
                <Stack spacing={1.5}>
                  {(session.status === 'running' || session.status === 'resuming') ? (
                    <Button
                      variant="outlined"
                      size="small"
                      onClick={handleInterrupt}
                      loading={interruptSessionMutation.isPending}
                      startIcon={<RefreshIcon />}
                      sx={{ alignSelf: 'flex-start' }}
                    >
                      请求中断
                    </Button>
                  ) : null}
                  <InterruptDecisionPanel
                    status={session.status}
                    resumeIdempotencyKey={resumeIdempotencyKey}
                    decisionDraft={decisionDraft}
                    onResumeIdempotencyKeyChange={setResumeIdempotencyKey}
                    onDecisionDraftChange={setDecisionDraft}
                    onResume={handleResume}
                    resumePending={resumeSessionMutation.isPending}
                  />
                </Stack>
              }
              advancedEventsPanel={<ResearchAdvancedEventsPanel events={session.events} />}
              onReset={reset}
            />
          }
          canvas={
            <ResearchCanvas
              model={canvasModel}
              exportButton={
                <Button
                  variant="contained"
                  color="success"
                  size="small"
                  startIcon={<DownloadIcon />}
                  onClick={handleExport}
                  loading={exporting}
                >
                  导出报告
                </Button>
              }
              artifactPanel={
                <ArtifactPanel
                  reportMd={session.report_md}
                  reportJson={session.report_json}
                  artifacts={session.artifacts}
                />
              }
            />
          }
        />
      )}

      <ErrorAlert error={mergedError} onClose={handleCloseError} />
    </Container>
  );
}

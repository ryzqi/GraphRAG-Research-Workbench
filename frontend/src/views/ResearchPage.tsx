'use client';

/**
 * 深度研究页面
 */
import { useCallback, useMemo, useState } from 'react';
import { Box, Stack } from '@mui/material';
import DownloadIcon from '@mui/icons-material/Download';
import { ResearchCanvas } from '../components/research/ResearchCanvas';
import { ResearchComposer } from '../components/research/ResearchComposer';
import { ResearchPlanningThread } from '../components/research/ResearchPlanningThread';
import { ResearchReportReader } from '../components/research/ResearchReportReader';
import { Button } from '../components/ui/Button';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { createExport, pollExportUntilDone } from '../services/exports';
import { buildResearchPageViewModel } from '../services/researchWorkbench';
import {
  useCreateResearchSession,
  useResearchSession,
  useStartResearchSession,
  useStopResearchSession,
  useSubmitResearchClarification,
  useUpdateResearchPlan,
} from '../hooks/queries/useResearch';
import { useSystemQueueHealth } from '../hooks/queries/useSystemQueueHealth';
import { getErrorMessage } from '../lib/errorHandler';
import { buildQueueHealthHint } from '../services/queueHealthDiagnostics';
import type { ResearchSessionAccepted } from '../types/researchEvents';
import { safeOpenDownloadUrl } from '../utils/urlValidation';
import {
  buildResearchStartRequest,
  validateResearchStartDraft,
} from './researchPageState';

export function ResearchPage() {
  const QUEUE_HEALTH_TRIGGER_SECONDS = 30;
  const createSessionMutation = useCreateResearchSession();
  const submitClarificationMutation = useSubmitResearchClarification();
  const updatePlanMutation = useUpdateResearchPlan();
  const startSessionMutation = useStartResearchSession();
  const stopSessionMutation = useStopResearchSession();

  const [question, setQuestion] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [acceptedSession, setAcceptedSession] = useState<ResearchSessionAccepted | null>(null);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clarificationDraft, setClarificationDraft] = useState('');
  const [planFeedbackDraft, setPlanFeedbackDraft] = useState('');
  const questionValidationError = error === '请输入研究问题' ? error : null;

  const sessionQuery = useResearchSession(sessionId ?? undefined, acceptedSession);
  const session = sessionQuery.data;

  const mergedError =
    error ??
    (createSessionMutation.error ? getErrorMessage(createSessionMutation.error) : null) ??
    (submitClarificationMutation.error
      ? getErrorMessage(submitClarificationMutation.error)
      : null) ??
    (updatePlanMutation.error ? getErrorMessage(updatePlanMutation.error) : null) ??
    (startSessionMutation.error ? getErrorMessage(startSessionMutation.error) : null) ??
    (stopSessionMutation.error ? getErrorMessage(stopSessionMutation.error) : null) ??
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
    if (submitClarificationMutation.error) {
      submitClarificationMutation.reset();
      return;
    }
    if (updatePlanMutation.error) {
      updatePlanMutation.reset();
      return;
    }
    if (startSessionMutation.error) {
      startSessionMutation.reset();
      return;
    }
    if (stopSessionMutation.error) {
      stopSessionMutation.reset();
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
      setClarificationDraft('');
      setPlanFeedbackDraft('');
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
    }
  }, [createSessionMutation, question]);

  const handleQuestionChange = useCallback((value: string) => {
    setQuestion(value);
    if (questionValidationError) {
      setError(null);
    }
  }, [questionValidationError]);

  const handleSubmitClarification = useCallback(async () => {
    if (!sessionId) {
      return;
    }

    const answer = clarificationDraft.trim();
    if (!answer) {
      setError('请输入补充说明');
      return;
    }

    setError(null);
    try {
      const nextAccepted = await submitClarificationMutation.mutateAsync({
        sessionId,
        body: { answer },
      });
      setAcceptedSession(nextAccepted);
      setClarificationDraft('');
      setPlanFeedbackDraft('');
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
    }
  }, [clarificationDraft, sessionId, submitClarificationMutation]);

  const handleUpdatePlan = useCallback(async () => {
    if (!sessionId) {
      return;
    }

    const feedback = planFeedbackDraft.trim();
    if (!feedback) {
      setError('请输入计划更新说明');
      return;
    }

    setError(null);
    try {
      const nextAccepted = await updatePlanMutation.mutateAsync({
        sessionId,
        body: { feedback },
      });
      setAcceptedSession(nextAccepted);
      setPlanFeedbackDraft('');
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
    }
  }, [planFeedbackDraft, sessionId, updatePlanMutation]);

  const handleStartExecution = useCallback(async () => {
    if (!sessionId) {
      return;
    }

    setError(null);
    try {
      const nextAccepted = await startSessionMutation.mutateAsync({ sessionId });
      setAcceptedSession(nextAccepted);
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
    }
  }, [sessionId, startSessionMutation]);

  const handleStop = useCallback(async () => {
    if (!sessionId) {
      return;
    }

    setError(null);
    try {
      const nextAccepted = await stopSessionMutation.mutateAsync({
        sessionId,
        body: { reason: '用户主动停止当前研究' },
      });
      setAcceptedSession(nextAccepted);
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
    }
  }, [sessionId, stopSessionMutation]);

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
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
    } finally {
      setExporting(false);
    }
  }, [session]);

  const reset = useCallback(() => {
    setSessionId(null);
    setAcceptedSession(null);
    setQuestion('');
    setError(null);
    setClarificationDraft('');
    setPlanFeedbackDraft('');
  }, []);

  const effectiveQuestion = session?.question ?? question;

  const pageModel = useMemo(
    () =>
      buildResearchPageViewModel({
        question: effectiveQuestion,
        status: session?.status ?? 'created',
        events: session?.events ?? [],
        artifacts: session?.artifacts ?? [],
        reportMd: session?.report_md ?? null,
        clarificationRequest: session?.clarification_request ?? null,
        planSnapshot: session?.plan_snapshot ?? null,
      }),
    [effectiveQuestion, session]
  );

  const latestQueuedTimestamp = useMemo(() => {
    const queuedEvents = (session?.events ?? []).filter(
      (event) => event.event_type === 'research.run.queued'
    );
    return queuedEvents.at(-1)?.timestamp ?? null;
  }, [session?.events]);
  const queuedWaitingSeconds = useMemo(() => {
    if (!latestQueuedTimestamp) {
      return null;
    }
    const timestampMs = Date.parse(latestQueuedTimestamp);
    if (Number.isNaN(timestampMs)) {
      return null;
    }
    return Math.max(0, Math.floor((Date.now() - timestampMs) / 1000));
  }, [latestQueuedTimestamp]);
  const waitingResearchSession = session?.status === 'queued';
  const queueHealthCheckEnabled =
    waitingResearchSession && (queuedWaitingSeconds ?? 0) >= QUEUE_HEALTH_TRIGGER_SECONDS;
  const queueHealthQuery = useSystemQueueHealth(Boolean(queueHealthCheckEnabled));
  const queueHealthHint = useMemo(() => {
    if (!queueHealthCheckEnabled) {
      return null;
    }
    if (queueHealthQuery.error) {
      return '队列健康检查失败，请确认后端与 Redis 可访问。';
    }
    return buildQueueHealthHint({
      snapshot: queueHealthQuery.data,
      waitingBootstrapBatch: false,
      batchProcessing: false,
      waitingResearchSession: true,
    });
  }, [queueHealthCheckEnabled, queueHealthQuery.data, queueHealthQuery.error]);

  return (
    <Box
      sx={{
        width: '100%',
        px: { xs: 2, md: 4 },
        py: { xs: 3, md: 4 },
        background: !sessionId ? 'transparent' : 'linear-gradient(180deg, #f8fbff 0%, #f4f7fb 42%, #eef3f9 100%)',
        minHeight: !sessionId ? { xs: 'calc(100vh - 96px)', md: 'calc(100vh - 120px)' } : undefined,
      }}
    >
      {!sessionId ? (
        <ResearchComposer
          question={question}
          loading={createSessionMutation.isPending}
          validationError={questionValidationError}
          onQuestionChange={handleQuestionChange}
          onStart={startResearch}
        />
      ) : !session ? (
        <LoadingSpinner text="加载研究任务..." />
      ) : pageModel.surface === 'clarifying' || pageModel.surface === 'planning' ? (
        <ResearchPlanningThread
          model={pageModel}
          actions={
            <Button variant="outlined" size="small" onClick={reset}>
              新研究
            </Button>
          }
          clarificationDraft={clarificationDraft}
          clarificationSubmitPending={submitClarificationMutation.isPending}
          planFeedbackDraft={planFeedbackDraft}
          planUpdatePending={updatePlanMutation.isPending}
          startPending={startSessionMutation.isPending}
          onClarificationDraftChange={setClarificationDraft}
          onSubmitClarification={handleSubmitClarification}
          onPlanFeedbackDraftChange={setPlanFeedbackDraft}
          onUpdatePlan={handleUpdatePlan}
          onStartExecution={handleStartExecution}
        />
      ) : pageModel.surface === 'final' ? (
        <ResearchReportReader
          model={pageModel}
          actions={
            <Stack direction="row" spacing={1}>
              <Button variant="outlined" size="small" onClick={reset}>
                新研究
              </Button>
            </Stack>
          }
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
        />
      ) : (
        <ResearchCanvas
          model={pageModel}
          actions={
            <Stack direction="row" spacing={1}>
              {(session.status === 'queued' || session.status === 'running') ? (
                <Button
                  variant="outlined"
                  size="small"
                  onClick={handleStop}
                  loading={stopSessionMutation.isPending}
                >
                  停止
                </Button>
              ) : null}
              <Button variant="outlined" size="small" onClick={reset}>
                新研究
              </Button>
            </Stack>
          }
        />
      )}

      <ErrorAlert error={mergedError} onClose={handleCloseError} />
      <ErrorAlert error={queueHealthHint} severity="warning" />
    </Box>
  );
}

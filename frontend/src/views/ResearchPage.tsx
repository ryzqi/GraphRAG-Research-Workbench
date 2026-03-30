'use client';

/**
 * 深度研究页面
 */
import { useCallback, useMemo, useState } from 'react';
import {
  Box,
  FormControlLabel,
  Container,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import DownloadIcon from '@mui/icons-material/Download';
import RefreshIcon from '@mui/icons-material/Refresh';
import { KnowledgeBaseSelector } from '../components/KnowledgeBaseSelector';
import { ArtifactPanel } from '../components/research/ArtifactPanel';
import { InterruptDecisionPanel } from '../components/research/InterruptDecisionPanel';
import { PlanPreviewPanel } from '../components/research/PlanPreviewPanel';
import { ResearchTimeline } from '../components/research/ResearchTimeline';
import { Button } from '../components/ui/Button';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { PageHeader } from '../components/ui/PageHeader';
import { StatusBadge } from '../components/ui/StatusBadge';
import { createExport, pollExportUntilDone } from '../services/exports';
import {
  useConfirmResearchPlan,
  useCreateResearchSession,
  useInterruptResearchSession,
  useResearchSession,
  useResumeResearchSession,
} from '../hooks/queries/useResearch';
import { useSelectableKnowledgeBases } from '../hooks/queries/useKnowledgeBases';
import { getErrorMessage } from '../lib/errorHandler';
import type { ResearchSessionAccepted, ResearchSessionStatus } from '../types/researchEvents';
import { safeOpenDownloadUrl } from '../utils/urlValidation';
import {
  buildResearchStartRequest,
  validateResearchStartDraft,
} from './researchPageState';

export function ResearchPage() {
  // 使用 SWR 自动去重并缓存知识库列表。
  const knowledgeBasesQuery = useSelectableKnowledgeBases();
  const knowledgeBases = knowledgeBasesQuery.data ?? [];

  const createSessionMutation = useCreateResearchSession();
  const confirmPlanMutation = useConfirmResearchPlan();
  const interruptSessionMutation = useInterruptResearchSession();
  const resumeSessionMutation = useResumeResearchSession();

  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [acceptedSession, setAcceptedSession] = useState<ResearchSessionAccepted | null>(null);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [allowExternal, setAllowExternal] = useState(true);
  const [requireConfirmation, setRequireConfirmation] = useState(false);
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
    (knowledgeBasesQuery.error ? getErrorMessage(knowledgeBasesQuery.error) : null) ??
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
    if (knowledgeBasesQuery.error) {
      knowledgeBasesQuery.refetch();
      return;
    }
    if (sessionQuery.error) {
      void sessionQuery.refetch();
    }
  };

  const toggleKb = useCallback((kbId: string) => {
    setSelectedKbIds((prev) =>
      prev.includes(kbId) ? prev.filter((id) => id !== kbId) : [...prev, kbId]
    );
  }, []);

  const startResearch = useCallback(async () => {
    const validationError = validateResearchStartDraft({
      question,
      selectedKbIds,
      allowExternal,
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
          selectedKbIds,
          allowExternal,
          requireConfirmation,
        })
      );

      setAcceptedSession(newSession);
      setSessionId(newSession.session_id);
      setResumeIdempotencyKey(`resume-${Date.now()}`);
    } catch (e) {
      setError(getErrorMessage(e));
    }
  }, [allowExternal, createSessionMutation, question, requireConfirmation, selectedKbIds]);

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
    setAllowExternal(true);
    setRequireConfirmation(false);
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

  return (
    <Container maxWidth="md" sx={{ py: 3 }}>
      <PageHeader title="深度研究" />

      {!sessionId ? (
        <Stack spacing={3}>
          <Typography variant="subtitle1" fontWeight={500}>
            选择知识库范围
          </Typography>

          <KnowledgeBaseSelector
            knowledgeBases={knowledgeBases}
            selectedIds={selectedKbIds}
            onToggle={toggleKb}
            loading={loading || knowledgeBasesQuery.isLoading}
          />

          <Box>
            <Typography variant="body2" sx={{ mb: 1 }}>
              研究问题
            </Typography>
            <TextField
              fullWidth
              multiline
              rows={4}
              placeholder="输入需要深度研究的问题..."
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
          </Box>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={allowExternal}
                  onChange={(event) => setAllowExternal(event.target.checked)}
                />
              }
              label={
                <Typography variant="body2" color="text.secondary">
                  允许外部研究
                </Typography>
              }
            />
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={requireConfirmation}
                  onChange={(event) => setRequireConfirmation(event.target.checked)}
                />
              }
              label={
                <Typography variant="body2" color="text.secondary">
                  执行前需要确认计划
                </Typography>
              }
            />
          </Stack>

          <Button
            variant="contained"
            onClick={startResearch}
            disabled={
              knowledgeBasesQuery.isLoading ||
              Boolean(
                validateResearchStartDraft({
                  question,
                  selectedKbIds,
                  allowExternal,
                })
              )
            }
            loading={loading}
            sx={{ alignSelf: 'flex-start' }}
          >
            开始研究
          </Button>
        </Stack>
      ) : !session ? (
        <LoadingSpinner text="加载研究任务..." />
      ) : (
        <Stack spacing={2}>
          <Paper
            variant="outlined"
            sx={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              p: 1.5,
              bgcolor: 'grey.50',
            }}
          >
            <Box>
              <Typography fontWeight={500}>研究问题</Typography>
              <Typography variant="body2" color="text.secondary">
                {question.trim()}
              </Typography>
            </Box>
            <Button
              variant="outlined"
              size="small"
              startIcon={<RefreshIcon />}
              onClick={reset}
            >
              新研究
            </Button>
          </Paper>

          {/* 状态与阶段摘要 */}
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
              <Typography fontWeight={500}>状态：</Typography>
              <StatusBadge
                status={statusPresentation?.badge ?? 'pending'}
                label={statusPresentation?.label ?? '等待中'}
              />
              {(session.status === 'running' || session.status === 'resuming') ? (
                <Button
                  variant="outlined"
                  size="small"
                  onClick={handleInterrupt}
                  loading={interruptSessionMutation.isPending}
                >
                  请求中断
                </Button>
              ) : null}
            </Stack>
          </Paper>

          <PlanPreviewPanel
            planSnapshot={session.plan_snapshot}
            status={session.status}
            onConfirm={handleConfirmPlan}
            confirmPending={confirmPlanMutation.isPending}
          />

          <ResearchTimeline events={session.events} />

          <InterruptDecisionPanel
            status={session.status}
            resumeIdempotencyKey={resumeIdempotencyKey}
            decisionDraft={decisionDraft}
            onResumeIdempotencyKeyChange={setResumeIdempotencyKey}
            onDecisionDraftChange={setDecisionDraft}
            onResume={handleResume}
            resumePending={resumeSessionMutation.isPending}
          />

          {session.report_md ? (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Stack
                direction="row"
                justifyContent="space-between"
                alignItems="center"
                sx={{ mb: 1.5 }}
              >
                <Typography variant="subtitle1" fontWeight={600}>
                  研究报告
                </Typography>
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
              </Stack>
            </Paper>
          ) : null}

          <ArtifactPanel
            reportMd={session.report_md}
            reportJson={session.report_json}
            artifacts={session.artifacts}
          />
        </Stack>
      )}

      <ErrorAlert error={mergedError} onClose={handleCloseError} />
    </Container>
  );
}

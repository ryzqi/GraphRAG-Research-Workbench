'use client';

/**
 * 深度研究页面
 */
import { useCallback, useMemo, useState } from 'react';
import {
  Box,
  Container,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import DownloadIcon from '@mui/icons-material/Download';
import RefreshIcon from '@mui/icons-material/Refresh';
import { KnowledgeBaseSelector } from '../components/KnowledgeBaseSelector';
import { Button } from '../components/ui/Button';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { PageHeader } from '../components/ui/PageHeader';
import { StatusBadge } from '../components/ui/StatusBadge';
import { createExport, pollExportUntilDone } from '../services/exports';
import { useCreateResearchSession, useResearchSession } from '../hooks/queries/useResearch';
import { useSelectableKnowledgeBases } from '../hooks/queries/useKnowledgeBases';
import { getErrorMessage } from '../lib/errorHandler';
import type { ResearchCanonicalCitation, ResearchSessionStatus } from '../types/researchEvents';
import { safeOpenDownloadUrl } from '../utils/urlValidation';

export function ResearchPage() {
  // 使用 SWR 自动去重并缓存知识库列表。
  const knowledgeBasesQuery = useSelectableKnowledgeBases();
  const knowledgeBases = knowledgeBasesQuery.data ?? [];

  const createSessionMutation = useCreateResearchSession();

  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [acceptedSession, setAcceptedSession] = useState<{
    session_id: string;
    status: ResearchSessionStatus;
    plan_snapshot: {
      research_brief: string;
      complexity: 'simple' | 'comparative' | 'complex';
      summary: string;
      subtasks: Array<{
        title: string;
        description: string;
        target_sources: Array<'kb' | 'web' | 'paper' | 'hybrid'>;
      }>;
      target_sources: Array<'kb' | 'web' | 'paper' | 'hybrid'>;
      budget_guidance?: string | null;
      confirmation_required: boolean;
    } | null;
  } | null>(null);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sessionQuery = useResearchSession(sessionId ?? undefined, acceptedSession);
  const session = sessionQuery.data;

  const loading = createSessionMutation.isPending;

  const mergedError =
    error ??
    (createSessionMutation.error ? getErrorMessage(createSessionMutation.error) : null) ??
    (knowledgeBasesQuery.error ? getErrorMessage(knowledgeBasesQuery.error) : null) ??
    (sessionQuery.error ? getErrorMessage(sessionQuery.error) : null);

  const citations = useMemo(() => {
    const raw = session?.report_json?.citations;
    if (!Array.isArray(raw)) {
      return [] as ResearchCanonicalCitation[];
    }
    return raw as ResearchCanonicalCitation[];
  }, [session?.report_json]);

  const handleCloseError = () => {
    if (error) {
      setError(null);
      return;
    }
    if (createSessionMutation.error) {
      createSessionMutation.reset();
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
    if (selectedKbIds.length === 0 || !question.trim()) {
      setError('请选择知识库并输入研究问题');
      return;
    }

    setError(null);
    setSessionId(null);
    setAcceptedSession(null);

    try {
      const newSession = await createSessionMutation.mutateAsync({
        question: question.trim(),
        selected_kb_ids: selectedKbIds,
        allow_external: false,
        require_confirmation: false,
      });

      setAcceptedSession(newSession);
      setSessionId(newSession.session_id);
    } catch (e) {
      setError(getErrorMessage(e));
    }
  }, [createSessionMutation, question, selectedKbIds]);

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

          <Button
            variant="contained"
            onClick={startResearch}
            disabled={knowledgeBasesQuery.isLoading || selectedKbIds.length === 0 || !question.trim()}
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
            </Stack>

            {session.plan_snapshot && (
              <Box>
                <Typography variant="body2" fontWeight={500} sx={{ mb: 1 }}>
                  计划摘要
                </Typography>
                <Box sx={{ fontSize: 13, color: 'text.secondary' }}>
                  <Box sx={{ mb: 0.5 }}>{session.plan_snapshot.research_brief}</Box>
                  <Box sx={{ mb: 0.5 }}>摘要：{session.plan_snapshot.summary}</Box>
                  <Box sx={{ mb: 0.5 }}>
                    来源：{session.plan_snapshot.target_sources.join(' / ')}
                  </Box>
                </Box>
              </Box>
            )}
          </Paper>

          {/* 研究报告 */}
          {session.report_md && (
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

              <Paper
                elevation={0}
                sx={{
                  p: 2,
                  bgcolor: 'grey.50',
                  whiteSpace: 'pre-wrap',
                  fontSize: 14,
                  lineHeight: 1.6,
                  maxHeight: 500,
                  overflowY: 'auto',
                }}
              >
                {session.report_md}
              </Paper>

              {citations.length > 0 && (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="body2" fontWeight={500} sx={{ mb: 1 }}>
                    引用 ({citations.length})
                  </Typography>
                  <Box sx={{ fontSize: 13, color: 'text.secondary' }}>
                    {citations.map((c, i) => {
                      const indexValue =
                        typeof c.source_id === 'string' && c.source_id.trim()
                          ? c.source_id
                          : i + 1;
                      const excerpt = typeof c.title === 'string' ? c.title : c.origin_url ?? c.url ?? '';

                      return (
                        <Box key={i} sx={{ mb: 0.5 }}>
                          [{indexValue}] {excerpt.slice(0, 100)}...
                        </Box>
                      );
                    })}
                  </Box>
                </Box>
              )}
            </Paper>
          )}
        </Stack>
      )}

      <ErrorAlert error={mergedError} onClose={handleCloseError} />
    </Container>
  );
}


/**
 * 深度研究页面
 */
import { useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
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
import { KnowledgeUpdateSubmit } from '../components/KnowledgeUpdateSubmit';
import { Button, ErrorAlert, LoadingSpinner, PageHeader, StatusBadge } from '../components/ui';
import { createExport, pollExportUntilDone } from '../services/exports';
import {
  researchKeys,
  useCreateResearchRun,
  useKnowledgeBases,
  useResearchReport,
  useResearchRun,
} from '../hooks/queries';
import { getErrorMessage } from '../lib/errorHandler';
import { safeOpenDownloadUrl } from '../utils/urlValidation';

export function ResearchPage() {
  // React Query：自动去重/缓存知识库列表（对齐 Vercel client-swr-dedup 思路）
  const knowledgeBasesQuery = useKnowledgeBases();
  const knowledgeBases = knowledgeBasesQuery.data ?? [];

  const queryClient = useQueryClient();
  const createRunMutation = useCreateResearchRun();

  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [runId, setRunId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runQuery = useResearchRun(runId ?? undefined);
  const run = runQuery.data;

  const reportQuery = useResearchReport(run?.status === 'succeeded' ? run.id : undefined);
  const report = reportQuery.data;

  const loading = createRunMutation.isPending;

  const mergedError =
    error ??
    (createRunMutation.error ? getErrorMessage(createRunMutation.error) : null) ??
    (knowledgeBasesQuery.error ? getErrorMessage(knowledgeBasesQuery.error) : null) ??
    (runQuery.error ? getErrorMessage(runQuery.error) : null) ??
    (reportQuery.error ? getErrorMessage(reportQuery.error) : null);

  const handleCloseError = () => {
    if (error) {
      setError(null);
      return;
    }
    if (createRunMutation.error) {
      createRunMutation.reset();
      return;
    }
    if (knowledgeBasesQuery.error) {
      knowledgeBasesQuery.refetch();
      return;
    }
    if (runQuery.error) {
      runQuery.refetch();
      return;
    }
    if (reportQuery.error) {
      reportQuery.refetch();
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
    setRunId(null);

    try {
      const newRun = await createRunMutation.mutateAsync({
        question: question.trim(),
        selected_kb_ids: selectedKbIds,
        allow_external: false,
        mode: 'single_agent',
      });

      // 直接回填 query cache，避免额外请求并立即启动 refetchInterval 轮询。
      queryClient.setQueryData(researchKeys.run(newRun.id), newRun);
      setRunId(newRun.id);
    } catch (e) {
      setError(getErrorMessage(e));
    }
  }, [createRunMutation, queryClient, question, selectedKbIds]);

  const handleExport = useCallback(async () => {
    if (!run) return;

    setExporting(true);
    setError(null);

    try {
      const job = await createExport({ type: 'research', run_id: run.id });
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
  }, [run]);

  const reset = useCallback(() => {
    setRunId(null);
    setQuestion('');
    setError(null);
  }, []);

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'running':
        return '研究中...';
      case 'succeeded':
        return '已完成';
      default:
        return '失败';
    }
  };

  return (
    <Container maxWidth="md" sx={{ py: 3 }}>
      <PageHeader title="深度研究" />

      {!runId ? (
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
      ) : !run ? (
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
                {run.question}
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
                status={run.status as 'running' | 'succeeded' | 'failed'}
                label={getStatusLabel(run.status)}
              />
            </Stack>

            {run.stage_summaries && Object.keys(run.stage_summaries).length > 0 && (
              <Box>
                <Typography variant="body2" fontWeight={500} sx={{ mb: 1 }}>
                  阶段摘要
                </Typography>
                <Box sx={{ fontSize: 13, color: 'text.secondary' }}>
                  {Object.entries(run.stage_summaries).map(([stage, summary]) => (
                    <Box key={stage} sx={{ mb: 0.5 }}>
                      <Typography
                        component="span"
                        variant="body2"
                        fontWeight={500}
                      >
                        {stage}：
                      </Typography>
                      {typeof summary === 'object'
                        ? JSON.stringify(summary)
                        : String(summary)}
                    </Box>
                  ))}
                </Box>
              </Box>
            )}
          </Paper>

          {/* 研究报告 */}
          {report && (
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
                {report.content_md}
              </Paper>

              {report.citations && report.citations.length > 0 && (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="body2" fontWeight={500} sx={{ mb: 1 }}>
                    引用 ({report.citations.length})
                  </Typography>
                  <Box sx={{ fontSize: 13, color: 'text.secondary' }}>
                    {report.citations.map((c, i) => {
                      const indexValue =
                        typeof c.index === 'number' || typeof c.index === 'string' ? c.index : i + 1;
                      const excerpt = typeof c.excerpt === 'string' ? c.excerpt : '';

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

          {/* 提交沉淀 */}
          {run.status === 'succeeded' && (
            <KnowledgeUpdateSubmit
              runId={run.id}
              kbIds={run.selected_kb_ids || []}
              reportContent={report?.content_md}
            />
          )}
        </Stack>
      )}

      <ErrorAlert error={mergedError} onClose={handleCloseError} />
    </Container>
  );
}

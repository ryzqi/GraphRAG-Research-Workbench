/**
 * 对比评测页面
 */
import { useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Box,
  Container,
  Grid,
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
import type { EvaluationRunCreateRequest } from '../services/evaluations';
import {
  evaluationKeys,
  useCreateEvaluationRun,
  useEvaluationRun,
  useKnowledgeBases,
} from '../hooks/queries';
import { safeOpenDownloadUrl } from '../utils/urlValidation';
import { getErrorMessage } from '../lib/errorHandler';

const DEFAULT_DATASET = {
  questions: [
    {
      id: 'q001',
      question: '什么是知识图谱？它与传统数据库有什么区别？',
      reference_answer: '知识图谱是一种用图结构表示实体及其关系的知识库。',
    },
  ],
};

export function EvaluationsPage() {
  // React Query：自动去重/缓存知识库列表（对齐 Vercel client-swr-dedup 思路）
  const knowledgeBasesQuery = useKnowledgeBases();
  const knowledgeBases = knowledgeBasesQuery.data ?? [];

  const queryClient = useQueryClient();
  const createRunMutation = useCreateEvaluationRun();

  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [datasetJson, setDatasetJson] = useState(JSON.stringify(DEFAULT_DATASET, null, 2));
  const [evalRunId, setEvalRunId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const evalRunQuery = useEvaluationRun(evalRunId ?? undefined);
  const evalRun = evalRunQuery.data;

  const loading = createRunMutation.isPending;

  const mergedError =
    error ??
    (createRunMutation.error ? getErrorMessage(createRunMutation.error) : null) ??
    (knowledgeBasesQuery.error ? getErrorMessage(knowledgeBasesQuery.error) : null) ??
    (evalRunQuery.error ? getErrorMessage(evalRunQuery.error) : null);

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
    if (evalRunQuery.error) {
      evalRunQuery.refetch();
    }
  };

  const toggleKb = useCallback((kbId: string) => {
    setSelectedKbIds((prev) =>
      prev.includes(kbId) ? prev.filter((id) => id !== kbId) : [...prev, kbId]
    );
  }, []);

  const startEvaluation = useCallback(async () => {
    if (selectedKbIds.length === 0) {
      setError('请选择至少一个知识库');
      return;
    }

    let dataset;
    try {
      dataset = JSON.parse(datasetJson);
    } catch {
      setError('数据集 JSON 格式错误');
      return;
    }

    setError(null);
    setEvalRunId(null);

    try {
      const req: EvaluationRunCreateRequest = {
        dataset,
        config: {
          selected_kb_ids: selectedKbIds,
          allow_external: false,
        },
      };

      const run = await createRunMutation.mutateAsync(req);

      // 直接回填 query cache，避免额外请求并立即启动轮询。
      queryClient.setQueryData(evaluationKeys.run(run.id), run);
      setEvalRunId(run.id);
    } catch (e) {
      setError(getErrorMessage(e));
    }
  }, [createRunMutation, datasetJson, queryClient, selectedKbIds]);

  const handleExport = useCallback(async () => {
    if (!evalRun) return;

    setExporting(true);
    setError(null);

    try {
      const job = await createExport({ type: 'evaluation', run_id: evalRun.id });
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
  }, [evalRun]);

  const reset = useCallback(() => {
    setEvalRunId(null);
    setError(null);
  }, []);

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'queued':
        return '排队中...';
      case 'running':
        return '评测中...';
      case 'succeeded':
        return '已完成';
      default:
        return '失败';
    }
  };

  const summary = evalRun?.summary;

  return (
    <Container maxWidth="lg" sx={{ py: 3 }}>
      <PageHeader title="对比评测" />
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        在同一问题集下运行单智能体与多智能体协作，对比评测效果
      </Typography>

      {!evalRunId ? (
        <Stack spacing={3}>
          {/* 知识库选择 */}
          <Box>
            <Typography variant="subtitle1" fontWeight={500} sx={{ mb: 1.5 }}>
              选择知识库范围
            </Typography>
            <KnowledgeBaseSelector
              knowledgeBases={knowledgeBases}
              selectedIds={selectedKbIds}
              onToggle={toggleKb}
              loading={loading || knowledgeBasesQuery.isLoading}
            />
          </Box>

          {/* 数据集编辑 */}
          <Box>
            <Typography variant="subtitle1" fontWeight={500} sx={{ mb: 1.5 }}>
              评测数据集 (JSON)
            </Typography>
            <TextField
              fullWidth
              multiline
              rows={12}
              value={datasetJson}
              onChange={(e) => setDatasetJson(e.target.value)}
              InputProps={{
                sx: { fontFamily: 'monospace', fontSize: 13 },
              }}
            />
          </Box>

          <Button
            variant="contained"
            onClick={startEvaluation}
            disabled={knowledgeBasesQuery.isLoading || selectedKbIds.length === 0}
            loading={loading}
            sx={{ alignSelf: 'flex-start' }}
          >
            开始评测
          </Button>
        </Stack>
      ) : !evalRun ? (
        <LoadingSpinner text="加载评测任务..." />
      ) : (
        <Stack spacing={2}>
          {/* 状态栏 */}
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
            <Stack direction="row" alignItems="center" spacing={1.5}>
              <Typography fontWeight={500}>状态：</Typography>
              <StatusBadge
                status={
                  evalRun.status === 'succeeded'
                    ? 'succeeded'
                    : evalRun.status === 'failed'
                      ? 'failed'
                      : 'running'
                }
                label={getStatusLabel(evalRun.status)}
              />
            </Stack>
            {summary?.completed_questions !== undefined && summary?.total_questions !== undefined && (
              <Typography variant="body2" color="text.secondary">
                进度：{summary.completed_questions}/{summary.total_questions}
              </Typography>
            )}
            <Stack direction="row" spacing={1}>
              {evalRun.status === 'succeeded' && (
                <Button
                  variant="contained"
                  color="success"
                  size="small"
                  startIcon={<DownloadIcon />}
                  onClick={handleExport}
                  loading={exporting}
                >
                  导出结果
                </Button>
              )}
              <Button
                variant="outlined"
                size="small"
                startIcon={<RefreshIcon />}
                onClick={reset}
              >
                新评测
              </Button>
            </Stack>
          </Paper>

          {/* 汇总指标 */}
          {summary && (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
                对比汇总
              </Typography>
              <Grid container spacing={2}>
                <Grid size={{ xs: 12, md: 6 }}>
                  <Paper elevation={0} sx={{ p: 2, bgcolor: 'primary.50', borderRadius: 2 }}>
                    <Typography fontWeight={500} sx={{ mb: 1 }}>
                      单智能体
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      平均得分: {summary.single_agent?.avg_score?.toFixed(1) ?? 'N/A'}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      平均耗时: {summary.single_agent?.avg_latency?.toFixed(0) ?? 'N/A'}ms
                    </Typography>
                  </Paper>
                </Grid>
                <Grid size={{ xs: 12, md: 6 }}>
                  <Paper elevation={0} sx={{ p: 2, bgcolor: 'success.50', borderRadius: 2 }}>
                    <Typography fontWeight={500} sx={{ mb: 1 }}>
                      多智能体协作
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      平均得分: {summary.multi_agent?.avg_score?.toFixed(1) ?? 'N/A'}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      平均耗时: {summary.multi_agent?.avg_latency?.toFixed(0) ?? 'N/A'}ms
                    </Typography>
                  </Paper>
                </Grid>
              </Grid>
            </Paper>
          )}

          {/* 题目明细 */}
          {summary?.case_results && summary.case_results.length > 0 && (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
                题目明细
              </Typography>
              <Stack spacing={1.5}>
                {summary.case_results.map((c, i) => (
                  <Paper
                    key={c.question_id}
                    variant="outlined"
                    sx={{
                      p: 1.5,
                      bgcolor: 'grey.50',
                      contentVisibility: 'auto',
                      containIntrinsicSize: '1px 160px',
                    }}
                  >
                    <Typography fontWeight={500} sx={{ mb: 1 }}>
                      {i + 1}. {c.question}
                    </Typography>
                    <Grid container spacing={1.5}>
                      <Grid size={{ xs: 12, md: 6 }}>
                        <Typography
                          variant="body2"
                          color="primary.main"
                          fontWeight={500}
                        >
                          单智能体 (得分: {c.single_score?.toFixed(1) ?? 'N/A'})
                        </Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                          {c.single_agent_answer || '无回答'}
                        </Typography>
                      </Grid>
                      <Grid size={{ xs: 12, md: 6 }}>
                        <Typography
                          variant="body2"
                          color="success.main"
                          fontWeight={500}
                        >
                          多智能体 (得分: {c.multi_score?.toFixed(1) ?? 'N/A'})
                        </Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                          {c.multi_agent_answer || '无回答'}
                        </Typography>
                      </Grid>
                    </Grid>
                    {c.reference_answer && (
                      <Typography
                        variant="caption"
                        color="text.disabled"
                        sx={{ mt: 1, display: 'block' }}
                      >
                        参考答案: {c.reference_answer}
                      </Typography>
                    )}
                  </Paper>
                ))}
              </Stack>
            </Paper>
          )}
        </Stack>
      )}

      <ErrorAlert error={mergedError} onClose={handleCloseError} />
    </Container>
  );
}

export default EvaluationsPage;

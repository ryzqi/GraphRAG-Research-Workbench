/**
 * 深度研究页面
 */
import { useCallback, useEffect, useState } from 'react';
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
import { Button, ErrorAlert, PageHeader, StatusBadge } from '../components/ui';
import type { AgentRun } from '../services/chats';
import { createExport, pollExportUntilDone } from '../services/exports';
import { type KnowledgeBase, listKnowledgeBases } from '../services/knowledgeBases';
import {
  type ResearchReport,
  createResearchRun,
  getResearchReport,
  getResearchRun,
} from '../services/research';
import { getErrorMessage } from '../lib/errorHandler';
import { usePolling } from '../hooks/usePolling';
import { safeOpenDownloadUrl } from '../utils/urlValidation';

export function ResearchPage() {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [run, setRun] = useState<AgentRun | null>(null);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 加载知识库列表
  useEffect(() => {
    listKnowledgeBases()
      .then((res) => setKnowledgeBases(res.items))
      .catch((e) => setError(getErrorMessage(e)));
  }, []);

  // 使用 usePolling 轮询研究状态
  usePolling(
    async (signal) => {
      if (!run) throw new Error('No run');
      return getResearchRun(run.id);
    },
    {
      enabled: !!run && run.status === 'running',
      interval: 2000,
      onSuccess: async (updated) => {
        setRun(updated);
        if (updated.status === 'succeeded') {
          try {
            const rpt = await getResearchReport(updated.id);
            setReport(rpt);
          } catch (e) {
            setError(getErrorMessage(e));
          }
        }
      },
      onError: (e) => setError(getErrorMessage(e)),
      shouldContinue: (data) => data.status === 'running',
    }
  );

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

    setLoading(true);
    setError(null);
    setRun(null);
    setReport(null);

    try {
      const newRun = await createResearchRun({
        question: question.trim(),
        selected_kb_ids: selectedKbIds,
        allow_external: false,
        mode: 'single_agent',
      });
      setRun(newRun);
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [selectedKbIds, question]);

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
    setRun(null);
    setReport(null);
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

      {!run ? (
        <Stack spacing={3}>
          <Typography variant="subtitle1" fontWeight={500}>
            选择知识库范围
          </Typography>

          <KnowledgeBaseSelector
            knowledgeBases={knowledgeBases}
            selectedIds={selectedKbIds}
            onToggle={toggleKb}
            loading={loading}
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
            disabled={selectedKbIds.length === 0 || !question.trim()}
            loading={loading}
            sx={{ alignSelf: 'flex-start' }}
          >
            开始研究
          </Button>
        </Stack>
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
              <StatusBadge status={run.status as 'running' | 'succeeded' | 'failed'}>
                {getStatusLabel(run.status)}
              </StatusBadge>
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
                    {report.citations.map((c, i) => (
                      <Box key={i} sx={{ mb: 0.5 }}>
                        [{c.index || i + 1}] {(c.excerpt as string)?.slice(0, 100)}...
                      </Box>
                    ))}
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

      <ErrorAlert error={error} onClose={() => setError(null)} />
    </Container>
  );
}

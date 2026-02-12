import { useEffect, useMemo, useState } from 'react';
import { Box, Collapse, IconButton, LinearProgress, Paper, Stack, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

export type PipelineStepStatus = 'started' | 'completed' | 'failed' | 'waiting_user' | 'skipped';

export interface PipelineStep {
  step_id: string;
  label: string;
  status: PipelineStepStatus;
  node?: string;
  message?: string;
  ts?: string;
  meta?: Record<string, unknown>;
}

interface PipelineProgressProps {
  steps: PipelineStep[];
  isStreaming: boolean;
}

const STEP_ORDER: Record<string, number> = {
  preprocess: 0,
  retrieve: 1,
  judge: 2,
  generate: 3,
  verify: 4,
  finalize: 5,
};

function sortSteps(steps: PipelineStep[]): PipelineStep[] {
  return [...steps].sort((a, b) => {
    const orderA = STEP_ORDER[a.step_id] ?? Number.MAX_SAFE_INTEGER;
    const orderB = STEP_ORDER[b.step_id] ?? Number.MAX_SAFE_INTEGER;
    if (orderA !== orderB) {
      return orderA - orderB;
    }
    return (a.ts ?? '').localeCompare(b.ts ?? '');
  });
}

function statusColor(status: PipelineStepStatus): string {
  switch (status) {
    case 'completed':
      return 'success.main';
    case 'failed':
      return 'error.main';
    case 'waiting_user':
      return 'warning.main';
    case 'skipped':
      return 'text.disabled';
    default:
      return 'info.main';
  }
}

function statusLabel(status: PipelineStepStatus): string {
  switch (status) {
    case 'completed':
      return '完成';
    case 'failed':
      return '失败';
    case 'waiting_user':
      return '等待输入';
    case 'skipped':
      return '跳过';
    default:
      return '进行中';
  }
}

export function PipelineProgress({ steps, isStreaming }: PipelineProgressProps) {
  const [expanded, setExpanded] = useState(isStreaming);
  const sorted = useMemo(() => sortSteps(steps), [steps]);
  const completedCount = sorted.filter((step) => step.status === 'completed').length;
  const current = sorted.find((step) => step.status === 'started' || step.status === 'waiting_user');
  const progressValue = sorted.length > 0 ? Math.min(100, (completedCount / sorted.length) * 100) : 0;

  useEffect(() => {
    if (isStreaming) {
      setExpanded(true);
      return;
    }
    setExpanded(false);
  }, [isStreaming]);

  if (sorted.length === 0) {
    return null;
  }

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        borderRadius: 2.5,
        bgcolor: (theme) =>
          theme.palette.mode === 'light' ? 'rgba(255,255,255,0.72)' : 'rgba(22,24,29,0.62)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
      }}
    >
      <Stack spacing={1}>
        <Stack direction="row" alignItems="center" spacing={1} justifyContent="space-between">
          <Box>
            <Typography variant="caption" color="text.secondary">
              执行进度
            </Typography>
            <Typography variant="body2" fontWeight={600}>
              {current
                ? `${current.label} · ${statusLabel(current.status)}`
                : `${completedCount}/${sorted.length} 阶段完成`}
            </Typography>
          </Box>
          <IconButton
            size="small"
            onClick={() => setExpanded((v) => !v)}
            aria-label={expanded ? '收起流程详情' : '展开流程详情'}
            sx={{
              transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 0.2s ease',
            }}
          >
            <ExpandMoreIcon fontSize="small" />
          </IconButton>
        </Stack>

        <LinearProgress
          variant="determinate"
          value={progressValue}
          sx={{
            height: 6,
            borderRadius: 99,
            bgcolor: 'action.hover',
          }}
        />

        <Collapse in={expanded} timeout={180}>
          <Stack spacing={0.75} sx={{ mt: 0.5 }}>
            {sorted.map((step) => (
              <Stack key={step.step_id} direction="row" spacing={1} alignItems="center">
                <Box
                  sx={{
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    bgcolor: statusColor(step.status),
                    flexShrink: 0,
                  }}
                />
                <Typography variant="caption" sx={{ minWidth: 70 }} color="text.secondary">
                  {step.label}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {statusLabel(step.status)}
                </Typography>
                {step.message && (
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 0.5 }}>
                    · {step.message}
                  </Typography>
                )}
              </Stack>
            ))}
          </Stack>
        </Collapse>
      </Stack>
    </Paper>
  );
}

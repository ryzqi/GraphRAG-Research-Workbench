import type { ReactNode } from 'react';
import { Alert, Box, Chip, Paper, Stack, Typography, type AlertColor } from '@mui/material';

import type { IngestionChipColor, IngestionSummaryMetrics } from './statusPresentation';

interface IngestionStatusOverviewCardProps {
  title?: string;
  description?: string | null;
  taskId?: string | null;
  batchId?: string | null;
  statusLabel?: string | null;
  statusColor?: IngestionChipColor;
  streamHint?: string | null;
  streamHintSeverity?: AlertColor;
  metrics: IngestionSummaryMetrics;
  uploadProgressText?: string | null;
  progressMessage?: string | null;
  errorMessage?: string | null;
  footerHint?: string | null;
  actions?: ReactNode;
}

const METRIC_META = [
  { key: 'succeededDocs', label: '成功', color: 'success.main' },
  { key: 'failedDocs', label: '失败', color: 'error.main' },
  { key: 'canceledDocs', label: '取消', color: 'text.secondary' },
  { key: 'processingDocs', label: '处理中', color: 'warning.main' },
  { key: 'succeededChunks', label: '分块', color: 'primary.main' },
] as const;

export function IngestionStatusOverviewCard({
  title = '导入状态总览',
  description,
  taskId,
  batchId,
  statusLabel,
  statusColor = 'default',
  streamHint,
  streamHintSeverity = 'info',
  metrics,
  uploadProgressText,
  progressMessage,
  errorMessage,
  footerHint,
  actions,
}: IngestionStatusOverviewCardProps) {
  return (
    <Paper
      variant='outlined'
      sx={{
        p: 2.25,
        borderRadius: 3,
        borderColor: 'divider',
        bgcolor: (theme) =>
          theme.palette.mode === 'light' ? 'background.paper' : 'background.default',
      }}
    >
      <Stack spacing={1.5}>
        <Stack
          direction='row'
          spacing={1}
          justifyContent='space-between'
          alignItems={{ xs: 'flex-start', md: 'center' }}
          flexWrap='wrap'
          useFlexGap
        >
          <Stack spacing={0.4}>
            <Typography variant='h6'>{title}</Typography>
            {description && (
              <Typography variant='body2' color='text.secondary'>
                {description}
              </Typography>
            )}
          </Stack>
          <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
            {taskId && <Chip label={`提交任务：${taskId}`} variant='outlined' size='small' />}
            {batchId && <Chip label={`批次：${batchId}`} variant='outlined' size='small' />}
            {statusLabel && <Chip label={statusLabel} color={statusColor} size='small' />}
          </Stack>
        </Stack>

        {streamHint && <Alert severity={streamHintSeverity}>{streamHint}</Alert>}

        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: {
              xs: 'repeat(2, minmax(0, 1fr))',
              md: 'repeat(5, minmax(0, 1fr))',
            },
            gap: 1,
          }}
        >
          {METRIC_META.map((metric) => (
            <Paper
              key={metric.key}
              variant='outlined'
              sx={{
                p: 1.1,
                borderRadius: 2,
                borderColor: 'divider',
                bgcolor: 'background.default',
              }}
            >
              <Typography variant='caption' color='text.secondary'>
                {metric.label}
              </Typography>
              <Typography variant='subtitle1' fontWeight={700} sx={{ color: metric.color }}>
                {metrics[metric.key]}
              </Typography>
            </Paper>
          ))}
        </Box>

        {uploadProgressText && (
          <Typography variant='body2' color='text.secondary'>
            {uploadProgressText}
          </Typography>
        )}
        {progressMessage && (
          <Typography variant='body2' color='text.secondary'>
            {progressMessage}
          </Typography>
        )}
        {errorMessage && (
          <Typography variant='body2' color='error.main'>
            {errorMessage}
          </Typography>
        )}
        {footerHint && (
          <Typography variant='caption' color='text.secondary'>
            {footerHint}
          </Typography>
        )}
        {actions}
      </Stack>
    </Paper>
  );
}

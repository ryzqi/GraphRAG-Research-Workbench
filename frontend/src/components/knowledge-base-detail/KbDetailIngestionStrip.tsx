import { Alert, Chip, Paper, Stack, Typography } from '@mui/material';

interface KbDetailIngestionStripProps {
  state: 'loading' | 'error' | 'idle' | 'active';
  statusLabel?: string | null;
  statusColor?: 'default' | 'success' | 'warning' | 'error' | 'info';
  summaryText?: string | null;
  helperText?: string | null;
  errorMessage?: string | null;
}

export function KbDetailIngestionStrip({
  state,
  statusLabel,
  statusColor = 'default',
  summaryText,
  helperText,
  errorMessage,
}: KbDetailIngestionStripProps) {
  if (state === 'error') {
    return (
      <Paper
        variant='outlined'
        sx={{
          p: { xs: 1.25, md: 1.5 },
          borderRadius: 3,
          borderColor: 'divider',
        }}
      >
        <Alert severity='error'>{errorMessage ?? '导入状态获取失败'}</Alert>
      </Paper>
    );
  }

  const message =
    state === 'loading'
      ? '正在同步最新导入状态…'
      : state === 'idle'
        ? '当前暂无活跃导入批次。'
        : summaryText ?? '当前批次处理中。';

  return (
    <Paper
      variant='outlined'
      sx={{
        p: { xs: 1.25, md: 1.5 },
        borderRadius: 3,
        borderColor: 'divider',
      }}
    >
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={1}
        justifyContent='space-between'
        alignItems={{ xs: 'flex-start', md: 'center' }}
      >
        <Stack spacing={0.35}>
          <Typography variant='overline' color='text.secondary'>
            导入状态
          </Typography>
          <Typography variant='body2'>{message}</Typography>
          {helperText && (
            <Typography variant='caption' color='text.secondary'>
              {helperText}
            </Typography>
          )}
        </Stack>

        {statusLabel && (
          <Chip
            label={statusLabel}
            color={statusColor}
            size='small'
            variant='outlined'
          />
        )}
      </Stack>
    </Paper>
  );
}
